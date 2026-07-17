from __future__ import annotations

import csv
import base64
import json
import mimetypes
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl import Workbook

from app import db
from app.assets import internet_logo_for, pump_logo_for, receipt_texture_path, revenue_stamp_path, signature_for
from app.book_lookup import dynamic_book, search_openlibrary_sync
from app.calculations import book_totals, fuel_row_amount, fuel_totals, internet_totals
from app.config import BASE_DIR, DB_PATH, OUTPUT_DIR
from app.fuel_prices import effective_lookup_date, fetch_goodreturns_petrol_price
from app.models import BookBill, DriverSalaryBill, FuelBill, FuelLogRow, InternetBill
from app.renderer import html_to_pdf, merge_pdfs, render_template
from app.sample_data import profile_backed_values, sample_payload
from app.utils import filename_for, month_label, month_name, output_month_dir

MODEL_BY_TYPE = {
    "internet": InternetBill,
    "driver": DriverSalaryBill,
    "book": BookBill,
    "fuel": FuelBill,
}

def month_output_dir(month: str) -> Path:
    path = OUTPUT_DIR / output_month_dir(month)
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_user_id() -> int:
    db.init_db()
    with db.connect() as conn:
        return db.get_or_create_user(conn)


def ensure_seeded() -> int:
    db.initialize_installation()
    return default_user_id()


def require_complete_profile(user_id: int) -> dict:
    with db.connect() as conn:
        profile = db.get_profile(conn, user_id)
    missing = db.missing_profile_fields(profile)
    if missing:
        raise ValueError(f"Complete Profile setup first. Missing: {', '.join(missing)}")
    return profile


def validate_payload(bill_type: str, payload: dict) -> InternetBill | DriverSalaryBill | BookBill | FuelBill:
    if bill_type not in MODEL_BY_TYPE:
        raise ValueError(f"unknown bill type: {bill_type}")
    return MODEL_BY_TYPE[bill_type].model_validate(payload)


def enrich_payload_assets(bill_type: str, payload: dict) -> dict:
    payload = dict(payload)
    if bill_type == "internet" and not payload.get("provider_logo_path"):
        provider = payload.get("provider_name") or payload.get("provider_logo_text") or ""
        payload["provider_logo_path"] = internet_logo_for(provider)
    if bill_type == "driver":
        if not payload.get("revenue_stamp_path") and not payload.get("revenue_stamp_asset_id"):
            payload["revenue_stamp_path"] = revenue_stamp_path()
        if not payload.get("signature_path") and not payload.get("signature_asset_id"):
            payload["signature_path"] = signature_for(payload.get("driver_name", ""))
    if bill_type == "fuel":
        rows = []
        for row in payload.get("rows", []):
            row = dict(row)
            if not row.get("vendor_logo_path"):
                row["vendor_logo_path"] = pump_logo_for(row.get("vendor", ""))
            rows.append(row)
        payload["rows"] = rows
    if bill_type == "book":
        payload = enrich_book_metadata(payload)
    return payload


def enrich_book_metadata(payload: dict) -> dict:
    payload = dict(payload)
    keyword = (payload.get("lookup_keyword") or payload.get("book_name") or "").strip()
    if not keyword:
        return payload
    if payload.get("author") and payload.get("publisher") and payload.get("description"):
        return payload
    try:
        result = next(iter(search_openlibrary_sync(keyword)), None)
    except Exception:
        payload["book_name"] = payload.get("book_name") or keyword
        payload["description"] = payload.get("description") or keyword
        return payload
    if not result:
        payload["book_name"] = payload.get("book_name") or keyword
        payload["description"] = payload.get("description") or keyword
        return payload
    payload["book_name"] = payload.get("book_name") or result.get("title") or keyword
    payload["author"] = payload.get("author") or result.get("author") or ""
    payload["publisher"] = payload.get("publisher") or result.get("publisher") or ""
    payload["description"] = payload.get("description") or result.get("description") or result.get("title") or ""
    return payload


def refresh_book_metadata(payload: dict) -> dict:
    payload = dict(payload)
    keyword = (payload.get("lookup_keyword") or "").strip() or "software engineering business"
    book = dynamic_book(keyword=keyword)
    book_title = book.get("title") or payload.get("book_name") or "Monthly Book"
    payload["book_name"] = book_title
    payload["author"] = book.get("author", "")
    payload["publisher"] = book.get("publisher", "")
    payload["description"] = book.get("description") or book_title
    return payload


def values_equivalent(left, right) -> bool:
    if left in (None, "") and right in (None, ""):
        return True
    if isinstance(left, (dict, list)) or isinstance(right, (dict, list)):
        return left == right
    if str(left).strip() == str(right).strip():
        return True
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except Exception:
        return False


def merge_profile_precedence(
    bill_type: str,
    month: str,
    profile: dict,
    saved_payload: dict,
    saved_audit: dict,
) -> dict:
    payload = dict(saved_payload)
    profile_values = profile_backed_values(bill_type, month, profile)
    for field, value in profile_values.items():
        audit_entry = saved_audit.get(field) or {}
        if audit_entry.get("source") != "manual_override":
            payload[field] = value
    return payload


def load_or_sample_payload(user_id: int, bill_type: str, month: str, db_path: Path = DB_PATH) -> dict:
    with db.connect(db_path) as conn:
        profile = db.get_profile(conn, user_id)
        instance = db.find_instance(conn, user_id, bill_type, month)
        if instance and instance["current_version_id"]:
            row = conn.execute(
                "SELECT source_json, field_audit_json FROM bill_versions WHERE id = ?",
                (instance["current_version_id"],),
            ).fetchone()
            if row:
                saved_payload = json.loads(row["source_json"])
                saved_audit = json.loads(row["field_audit_json"] or "{}")
                if bill_type == "fuel" and (saved_audit.get("rows") or {}).get("source") != "manual_override":
                    return sample_payload(bill_type, month, profile)
                return merge_profile_precedence(bill_type, month, profile, saved_payload, saved_audit)
    return sample_payload(bill_type, month, profile)


def field_audit(
    bill_type: str,
    month: str,
    payload: dict,
    profile: dict,
    manual_override_fields: set[str] | None = None,
) -> dict:
    manual_override_fields = manual_override_fields or set()
    profile_values = profile_backed_values(bill_type, month, profile)
    audit = {}
    for key, value in payload.items():
        if key == "rows":
            audit[key] = {
                "source": "manual_override" if key in manual_override_fields else "generated_from_profile_and_price_lookup",
                "row_count": len(value),
            }
        elif key in manual_override_fields:
            audit[key] = {"source": "manual_override"}
        elif key in profile_values:
            audit[key] = {
                "source": "profile_default" if values_equivalent(value, profile_values[key]) else "manual_override"
            }
        elif isinstance(value, dict):
            audit[key] = {child_key: {"source": "user_input_or_calculated"} for child_key in value}
        else:
            audit[key] = {"source": "user_input_or_generated"}
    return audit


def context_for(bill_type: str, model, month: str) -> dict:
    if bill_type == "internet":
        totals = internet_totals(model)
    elif bill_type == "book":
        totals = book_totals(model)
    elif bill_type == "fuel":
        totals = fuel_totals(model)
    else:
        totals = {}
    context = {
        "bill": model,
        "month": month,
        "month_label": month_label(month),
        "month_name": month_name(month),
        "totals": totals,
        "compliance_note": "Generated from user-provided or user-verified reimbursement data. Verify source records before upload.",
    }
    if bill_type == "driver":
        context["revenue_stamp"] = asset_data_uri(model.revenue_stamp_asset_id) or project_image_data_uri(model.revenue_stamp_path)
        context["signature"] = asset_data_uri(model.signature_asset_id) or project_image_data_uri(model.signature_path)
    if bill_type == "internet":
        context["provider_logo"] = project_image_data_uri(model.provider_logo_path)
    return context


def fuel_receipt_contexts(fuel: FuelBill, month: str) -> list[dict]:
    base_context = context_for("fuel", fuel, month)
    receipt_contexts = []
    for idx, row in enumerate(fuel.rows, start=1):
        receipt_contexts.append(
            {
                **base_context,
                "row": row,
                "row_number": idx,
                "amount": fuel_row_amount(row.litres, row.petrol_price_per_litre),
                "actual_receipt_image": project_image_data_uri(row.actual_receipt_image_path),
                "vendor_logo_image": project_image_data_uri(row.vendor_logo_path),
                "receipt_texture": project_image_data_uri(receipt_texture_path()),
            }
        )
    return receipt_contexts


def asset_data_uri(asset_id: int | None) -> str | None:
    if not asset_id:
        return None
    with db.connect() as conn:
        asset = db.get_asset(conn, int(asset_id))
    if not asset:
        return None
    path = Path(asset["path"])
    if not path.exists():
        return None
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def project_image_data_uri(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    try:
        path.resolve().relative_to(BASE_DIR.resolve())
    except ValueError as exc:
        raise ValueError("actual receipt image paths must be inside this project directory") from exc
    if not path.exists():
        return None
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    if not mime_type.startswith("image/"):
        raise ValueError("actual receipt attachment must be an image")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def preview_html(user_id: int, bill_type: str, month: str, payload: dict | None = None) -> tuple[str, dict]:
    require_complete_profile(user_id)
    payload = enrich_payload_assets(bill_type, payload or load_or_sample_payload(user_id, bill_type, month))
    model = validate_payload(bill_type, payload)
    if bill_type == "fuel":
        context = context_for("fuel", model, month)
        context["receipts"] = fuel_receipt_contexts(model, month)
        return render_template("bills/fuel_preview.html", context), model.model_dump(mode="json")
    return render_template(f"bills/{bill_type}.html", context_for(bill_type, model, month)), model.model_dump(mode="json")


def write_xlsx_logbook(fuel: FuelBill, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Fuel Logbook"
    ws.append([f"LOG BOOK ({month_label(fuel.month)})"])
    ws.append(["Date", "From", "To", "KM.Traveled", "Purpose of Travel"])
    travel_rows = [row for row in fuel.rows if row.km_travelled > 0]
    for row in travel_rows:
        ws.append([row.date.strftime("%-d-%b-%y"), row.from_city, row.to_city, float(row.km_travelled), row.purpose])
    ws.append([])
    ws.append(["", "", "Total Running", float(fuel_totals(fuel)["total_km"]), ""])
    ws.append([])
    ws.append(["Bills Attached"])
    ws.append(["S.No", "Date", "Ltrs", "Cost Per Lt (as per Bill)", "Total Amount", "Price Source"])
    for idx, row in enumerate(fuel.rows, start=1):
        ws.append(
            [
                idx,
                row.date.strftime("%-d-%b-%y"),
                float(row.litres),
                float(row.petrol_price_per_litre),
                int(fuel_row_amount(row.litres, row.petrol_price_per_litre)),
                row.price_source,
            ]
        )
    ws.append(["", "", float(fuel_totals(fuel)["total_litres"]), "", int(fuel_totals(fuel)["total_amount"]), ""])
    ws.append([])
    ws.append(["Emp Signature", fuel.employee_name])
    ws.append(["Emp Code", fuel.employee_code])
    for col in "ABCDEF":
        ws.column_dimensions[col].width = 24
    wb.save(output_path)
    return output_path


def generate_bill(
    user_id: int,
    bill_type: str,
    month: str,
    payload: dict | None = None,
    manual_override_fields: set[str] | None = None,
) -> dict:
    require_complete_profile(user_id)
    if bill_type == "all":
        return {"generated": [generate_bill(user_id, key, month, payload=None) for key in ("internet", "driver", "book", "fuel")]}
    # An explicit payload (e.g. the book form) is what the user previewed, so honor it
    # verbatim. Only pull a fresh book when no specific payload was supplied — the
    # interactive generator already loads a fresh book each time its page is opened.
    payload_supplied = payload is not None
    payload = enrich_payload_assets(bill_type, payload or load_or_sample_payload(user_id, bill_type, month))
    if bill_type == "book" and not payload_supplied:
        payload = refresh_book_metadata(payload)
    model = validate_payload(bill_type, payload)
    out_dir = month_output_dir(month)
    html, normalized = preview_html(user_id, bill_type, month, payload)
    html_path = out_dir / filename_for(bill_type, month, "html")
    html_path.write_text(html, encoding="utf-8")
    extra_outputs: dict[str, str | list[str]] = {}

    if bill_type == "fuel":
        fuel = FuelBill.model_validate(normalized)
        logbook_xlsx = out_dir / filename_for("fuel_logbook", month, "xlsx")
        write_xlsx_logbook(fuel, logbook_xlsx)
        logbook_pdf = out_dir / filename_for("fuel_logbook", month, "pdf")
        logbook_html = render_template("bills/fuel_logbook.html", context_for("fuel", fuel, month))
        html_to_pdf(logbook_html, logbook_pdf)
        receipt_dir = out_dir / "fuel_receipts"
        receipt_paths = []
        for idx, receipt_context in enumerate(fuel_receipt_contexts(fuel, month), start=1):
            receipt_html = render_template("bills/fuel_receipt.html", receipt_context)
            receipt_pdf = receipt_dir / f"Fuel Receipt {idx:02d} {month_label(month)}.pdf"
            html_to_pdf(receipt_html, receipt_pdf)
            receipt_paths.append(receipt_pdf)
        pdf_path = out_dir / filename_for("fuel", month, "pdf")
        merge_pdfs([logbook_pdf, *receipt_paths], pdf_path)
        extra_outputs = {
            "fuel_logbook_xlsx": str(logbook_xlsx),
            "fuel_logbook_pdf": str(logbook_pdf),
            "fuel_receipts": [str(path) for path in receipt_paths],
        }
    else:
        pdf_path = out_dir / filename_for(bill_type, month, "pdf")
        html_to_pdf(html, pdf_path)

    with db.connect() as conn:
        profile = db.get_profile(conn, user_id)
        instance = db.find_instance(conn, user_id, bill_type, month)
        instance_id = int(instance["id"]) if instance else db.create_instance(conn, user_id, bill_type, month)
        version_id = db.add_version(
            conn,
            instance_id,
            normalized,
            field_audit(bill_type, month, normalized, profile, manual_override_fields),
            str(html_path),
            str(pdf_path),
            extra_outputs,
        )
        version_row = conn.execute("SELECT version_number FROM bill_versions WHERE id = ?", (version_id,)).fetchone()
        version_number = int(version_row["version_number"])
        version_dir = out_dir / "versions"
        version_dir.mkdir(parents=True, exist_ok=True)
        version_html = version_dir / f"{bill_type}-v{version_number}.html"
        version_pdf = version_dir / f"{bill_type}-v{version_number}.pdf"
        shutil.copyfile(html_path, version_html)
        shutil.copyfile(pdf_path, version_pdf)
        conn.execute(
            "UPDATE bill_versions SET html_path = ?, pdf_path = ? WHERE id = ?",
            (str(version_html), str(version_pdf), version_id),
        )
        if bill_type == "fuel":
            conn.execute("DELETE FROM fuel_log_rows WHERE bill_instance_id = ?", (instance_id,))
            for row in normalized["rows"]:
                conn.execute(
                    "INSERT INTO fuel_log_rows(bill_instance_id, row_json, created_at) VALUES (?, ?, ?)",
                    (instance_id, db.json_dump(row), db.now_iso()),
                )
    return {"bill_type": bill_type, "month": month, "version_id": version_id, "html_path": str(html_path), "pdf_path": str(pdf_path), "extra_outputs": extra_outputs}


def export_bundle(month: str) -> Path:
    out_dir = month_output_dir(month)
    bundle = out_dir / f"reimbursement_bundle_{month_label(month).replace(' ', '_')}.zip"
    expected = [
        out_dir / filename_for("internet", month, "pdf"),
        out_dir / filename_for("driver", month, "pdf"),
        out_dir / filename_for("book", month, "pdf"),
        out_dir / filename_for("fuel_logbook", month, "xlsx"),
        out_dir / filename_for("fuel_logbook", month, "pdf"),
        out_dir / filename_for("fuel", month, "pdf"),
    ]
    with ZipFile(bundle, "w", ZIP_DEFLATED) as zip_file:
        for path in expected:
            if path.exists():
                zip_file.write(path, arcname=path.name)
    return bundle


def parse_fuel_items(items: list[dict], profile: dict, month: str) -> dict:
    rows = []
    for item in items:
        row_date = date.fromisoformat(item["date"])
        raw_price = (item.get("petrol_price_per_litre") or "").strip()
        raw_source = (item.get("price_source") or "").strip()
        if raw_price:
            petrol_price = Decimal(raw_price)
            price_source = raw_source
        else:
            price_row = fetch_and_store_fuel_price(item["fuel_city"], row_date)
            if not price_row:
                raise ValueError(f"No fuel price source found for {item['fuel_city']} on or before {row_date.isoformat()}")
            petrol_price = Decimal(str(price_row["price_per_litre"]))
            source_parts = [price_row["source_type"], price_row["price_date"]]
            if price_row["source_url"]:
                source_parts.append(price_row["source_url"])
            if price_row["note"]:
                source_parts.append(price_row["note"])
            if row_date > date.today():
                source_parts.append(
                    f"future travel date {row_date.isoformat()}; latest available price as of {date.today().isoformat()}"
                )
            price_source = raw_source or ": ".join(source_parts)
        if not price_source:
            raise ValueError("price_source is required when petrol_price_per_litre is provided manually")
        rows.append(
            FuelLogRow(
                date=row_date,
                receipt_time=item.get("receipt_time") or "08:32",
                from_city=item["from_city"],
                to_city=item["to_city"],
                km_travelled=Decimal(item["km_travelled"]),
                purpose=item["purpose"],
                fuel_city=item["fuel_city"],
                litres=Decimal(item["litres"]),
                petrol_price_per_litre=petrol_price,
                vendor=item["vendor"],
                vendor_logo_path=item.get("vendor_logo_path") or None,
                pump_address=item.get("pump_address", ""),
                pump_phone=item.get("pump_phone", ""),
                receipt_number=item["receipt_number"],
                vehicle_number=profile["vehicle_number"],
                customer_name=profile["employee_name"].split()[0],
                price_source=price_source,
                actual_receipt_image_path=item.get("actual_receipt_image_path") or None,
            )
        )
    return FuelBill(
        employee_name=profile["employee_name"],
        employee_code=profile["employee_code"],
        vehicle_number=profile["vehicle_number"],
        month=month,
        receipt_template=profile.get("_receipt_template", "1"),
        rows=rows,
    ).model_dump(mode="json")


def parse_fuel_csv(text: str, profile: dict, month: str) -> dict:
    reader = csv.DictReader(line for line in text.splitlines() if line.strip())
    return parse_fuel_items(list(reader), profile, month)


def fetch_and_store_fuel_price(city: str, row_date: date):
    lookup_date = effective_lookup_date(row_date)
    fetched = fetch_goodreturns_petrol_price(city, lookup_date)
    with db.connect() as conn:
        existing = db.lookup_fuel_price(conn, city, fetched.effective_date.isoformat())
        # Only treat it as already-stored when the exact effective date matches;
        # the cache lookup can otherwise return a nearby same-month row and we
        # would mis-attribute this price to that row's date.
        if (
            existing
            and existing["price_date"] == fetched.effective_date.isoformat()
            and existing["source_type"] == fetched.source_name
            and str(existing["price_per_litre"]) == str(fetched.price_per_litre)
        ):
            return existing
        if row_date <= lookup_date:
            note_parts = [f"Fetched for requested date {fetched.requested_date.isoformat()}"]
        else:
            note_parts = [
                f"Future travel date {row_date.isoformat()}; "
                f"used latest available price as of {lookup_date.isoformat()}"
            ]
        if fetched.approximate and fetched.note:
            note_parts.append(fetched.note)
        conn.execute(
            """
            INSERT OR IGNORE INTO fuel_price_sources(city, price_date, price_per_litre, source_type, source_url, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                city,
                fetched.effective_date.isoformat(),
                str(fetched.price_per_litre),
                fetched.source_name,
                fetched.source_url,
                "; ".join(note_parts),
                db.now_iso(),
            ),
        )
        return db.lookup_fuel_price(conn, city, fetched.effective_date.isoformat())
