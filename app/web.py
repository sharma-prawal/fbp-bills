from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.book_lookup import search_openlibrary
from app.calculations import fuel_totals, internet_totals
from app.config import ASSETS_DIR, OUTPUT_DIR
from app.models import BookBill, DriverSalaryBill, FuelBill, InternetBill, TaxFields
from app.registry import BILL_TYPES
from app.renderer import output_url, render_template
from app.sample_data import sample_payload
from app.services import default_user_id, enrich_payload_assets, ensure_seeded, export_bundle, generate_bill, load_or_sample_payload, parse_fuel_csv, parse_fuel_items, preview_html
from app.utils import month_label, output_month_dir, parse_month

app = FastAPI(title="FBP Bills")
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

PROFILE_SETUP_ALLOWED_PATHS = {
    "/profile",
    "/service-worker.js",
}


def user_id() -> int:
    return ensure_seeded()


@app.middleware("http")
async def require_profile_setup(request: Request, call_next):
    uid = ensure_seeded()
    path = request.url.path
    allowed = (
        path in PROFILE_SETUP_ALLOWED_PATHS
        or path.startswith("/static/")
        or path == "/favicon.ico"
    )
    if not allowed:
        with db.connect() as conn:
            profile = db.get_profile(conn, uid)
        if not db.profile_is_complete(profile):
            return RedirectResponse("/profile?setup=1", status_code=303)
    return await call_next(request)


def selected_month(value: str = "") -> str:
    month = value.strip() or date.today().strftime("%Y-%m")
    try:
        parse_month(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return month


def template(name: str, request: Request, **context) -> HTMLResponse:
    html = render_template(name, {"request": request, **context})
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def versioned_output_url(path: Path) -> str:
    url = output_url(str(path))
    if not path.exists():
        return url
    return f"{url}?v={int(path.stat().st_mtime)}"


def version_view_rows(rows) -> list[dict]:
    rendered = []
    for row in rows:
        item = dict(row)
        item["extra_outputs"] = json.loads(item.get("extra_outputs_json") or "{}")
        rendered.append(item)
    return rendered


def asset_options(user_id: int) -> dict[str, list[dict]]:
    with db.connect() as conn:
        return {
            "revenue_stamp": [dict(row) for row in db.list_assets(conn, user_id, "revenue_stamp")],
            "signature": [dict(row) for row in db.list_assets(conn, user_id, "signature")],
        }


def selected_asset_id(form, field_name: str) -> int | None:
    raw = str(form.get(field_name) or "").strip()
    return int(raw) if raw else None


def form_float(form, field_name: str, fallback: float) -> float:
    raw = str(form.get(field_name) or "").strip()
    if not raw:
        return fallback
    return float(raw)


def readiness_items(bill_type: str, payload: dict, profile: dict) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    items.append({"label": "Profile", "value": "defaults loaded", "state": "ready"})
    if bill_type == "internet":
        bill = InternetBill.model_validate(payload)
        totals = internet_totals(bill)
        items.extend(
            [
                {"label": "Bill date", "value": bill.bill_date.isoformat(), "state": "ready"},
                {"label": "Tax total", "value": f"INR {totals['total_amount']}", "state": "ready"},
                {"label": "Logo", "value": "matched asset" if bill.provider_logo_path else "text fallback", "state": "ready" if bill.provider_logo_path else "warn"},
            ]
        )
    elif bill_type == "driver":
        bill = DriverSalaryBill.model_validate(payload)
        items.extend(
            [
                {"label": "Salary", "value": f"INR {bill.salary_amount}", "state": "ready"},
                {"label": "Stamp", "value": "asset ready" if bill.revenue_stamp_path or bill.revenue_stamp_asset_id else "missing", "state": "ready" if bill.revenue_stamp_path or bill.revenue_stamp_asset_id else "warn"},
                {"label": "Signature", "value": "asset ready" if bill.signature_path or bill.signature_asset_id else "missing", "state": "ready" if bill.signature_path or bill.signature_asset_id else "warn"},
            ]
        )
    elif bill_type == "book":
        bill = BookBill.model_validate(payload)
        items.extend(
            [
                {"label": "Metadata", "value": "loaded" if bill.author and bill.publisher else "needs review", "state": "ready" if bill.author and bill.publisher else "warn"},
                {"label": "Price", "value": f"INR {bill.price}", "state": "ready" if bill.price_confirmed else "warn"},
                {"label": "Receipt date", "value": bill.receipt_date.isoformat(), "state": "ready"},
            ]
        )
    elif bill_type == "fuel":
        bill = FuelBill.model_validate(payload)
        totals = fuel_totals(bill)
        source_count = len([row for row in bill.rows if row.price_source.strip()])
        items.extend(
            [
                {"label": "Rows", "value": f"{len(bill.rows)} receipts", "state": "ready"},
                {"label": "Price sources", "value": f"{source_count}/{len(bill.rows)} recorded", "state": "ready" if source_count == len(bill.rows) else "warn"},
                {"label": "Total", "value": f"INR {totals['total_amount']}", "state": "ready"},
            ]
        )
    return items


def frame_preview_html(html: str, bill_type: str) -> str:
    # Override print positioning for the interactive iframe and fit the widest
    # rendered page to the available viewport.
    natural_width = 1587 if bill_type in ("driver", "fuel") else 794
    style_and_script = """
<style>
  html {
    background: #FAF7F2 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: auto !important;
  }
  body {
    background: #FAF7F2 !important;
    margin: 0 !important;
    padding: 24px 16px !important;
    min-height: 100vh !important;
    box-sizing: border-box !important;
    overflow: visible !important;
    transform: none !important;
    width: auto !important;
    zoom: normal !important;
  }
  
  /* Reset print-specific position offsets for interactive previewing */
  .logbook { margin-top: 20px !important; margin-bottom: 20px !important; }
  .receipt { margin-top: 20px !important; margin-bottom: 20px !important; }
  .frame { margin-top: 20px !important; }
  
  #preview-scale-container {
    width: max-content;
    max-width: none;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    transform-origin: top left;
    transition: zoom 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  }
  
  /* Apply visual luxury paper sheets to pages */
  .packet-page, main.invoice, main.frame, main.receipt, main.book-page {
    background: #ffffff !important;
    box-shadow: 0 10px 40px rgba(142, 117, 88, 0.12) !important;
    border: 1px solid rgba(142, 117, 88, 0.2) !important;
    margin-bottom: 32px !important;
    box-sizing: border-box !important;
    margin-top: 20px !important;
  }
</style>
<script>
  function adjustPreviewScale() {
    const container = document.getElementById('preview-scale-container');
    if (!container) return;
    
    container.style.zoom = '1';
    const configuredNaturalWidth = __NATURAL_WIDTH__;
    const pages = document.querySelectorAll(
      '.logbook, .receipt-wrap, .scan-page, main.invoice, main.frame, main.receipt, main.book-page'
    );
    if (pages.length === 0) return;
    
    let naturalWidth = Math.max(
      ...Array.from(pages, page => page.offsetWidth)
    );
    if (!naturalWidth || naturalWidth < 100) {
      naturalWidth = configuredNaturalWidth;
    }
    naturalWidth = Math.min(naturalWidth, configuredNaturalWidth);
    
    const availableWidth = Math.max(240, document.documentElement.clientWidth - 32);
    const scale = Math.min(1, availableWidth / naturalWidth);
    
    container.style.width = `${naturalWidth}px`;
    container.style.zoom = `${scale}`;
  }
  
  window.addEventListener('load', () => {
    const images = document.querySelectorAll('img');
    images.forEach(img => img.addEventListener('load', adjustPreviewScale));
    adjustPreviewScale();
  });
  window.addEventListener('resize', adjustPreviewScale);
</script>
</head>
""".replace("__NATURAL_WIDTH__", str(natural_width))
    html = html.replace("</head>", style_and_script)
    html = html.replace("<body>", '<body><div id="preview-scale-container">')
    html = html.replace("</body>", '</div></body>')
    return html


def latest_versions(rows: list[dict]) -> list[dict]:
    latest: dict[int, dict] = {}
    for row in rows:
        instance_id = int(row["instance_id"])
        current = latest.get(instance_id)
        if current is None or int(row["version_number"]) > int(current["version_number"]):
            latest[instance_id] = row
    return sorted(latest.values(), key=lambda row: row["generated_at"], reverse=True)


def filter_versions(rows: list[dict], month: str = "", bill_type: str = "", latest_only: bool = True) -> list[dict]:
    filtered = rows
    if month:
        filtered = [row for row in filtered if row["month"] == month]
    if bill_type:
        filtered = [row for row in filtered if row["bill_type"] == bill_type]
    if latest_only:
        filtered = latest_versions(filtered)
    return filtered


def manual_fuel_items_from_form(form) -> list[dict]:
    def values(name: str) -> list[str]:
        return [str(value) for value in form.getlist(name)]

    def value_at(name: str, idx: int) -> str:
        field_values = values(name)
        return field_values[idx] if idx < len(field_values) else ""

    dates = form.getlist("row_date")
    items = []
    for idx, row_date in enumerate(dates):
        if not str(row_date).strip():
            continue
        items.append(
            {
                "date": str(row_date),
                "from_city": value_at("row_from_city", idx),
                "to_city": value_at("row_to_city", idx),
                "km_travelled": value_at("row_km_travelled", idx),
                "purpose": value_at("row_purpose", idx),
                "fuel_city": value_at("row_fuel_city", idx),
                "litres": value_at("row_litres", idx),
                "petrol_price_per_litre": value_at("row_petrol_price_per_litre", idx),
                "vendor": value_at("row_vendor", idx),
                "vendor_logo_path": value_at("row_vendor_logo_path", idx),
                "pump_address": value_at("row_pump_address", idx),
                "pump_phone": value_at("row_pump_phone", idx),
                "receipt_number": value_at("row_receipt_number", idx),
                "price_source": value_at("row_price_source", idx),
                "actual_receipt_image_path": value_at("row_actual_receipt_image_path", idx),
            }
        )
    return items


async def save_uploaded_asset(user_id: int, upload: UploadFile | None, asset_type: str) -> int | None:
    if not upload or not upload.filename:
        return None
    content_type = upload.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail=f"{asset_type} must be an image file")
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail=f"{asset_type} must be PNG, JPG, JPEG, or WEBP")
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", Path(upload.filename).stem).strip("-") or asset_type
    asset_dir = ASSETS_DIR / str(user_id) / asset_type
    asset_dir.mkdir(parents=True, exist_ok=True)
    path = asset_dir / f"{db.now_iso().replace(':', '').replace('.', '')}-{safe_name}{suffix}"
    content = await upload.read()
    path.write_bytes(content)
    with db.connect() as conn:
        return db.create_asset(conn, user_id, asset_type, upload.filename, str(path))


@app.get("/service-worker.js")
def clear_service_worker() -> PlainTextResponse:
    script = """
self.addEventListener('install', event => self.skipWaiting());
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map(key => caches.delete(key)));
    await self.registration.unregister();
  })());
});
"""
    return PlainTextResponse(script.strip(), media_type="application/javascript", headers={"Cache-Control": "no-store"})


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, month: str = "") -> HTMLResponse:
    month = selected_month(month)
    uid = user_id()
    with db.connect() as conn:
        profile = db.get_profile(conn, uid)
        versions = version_view_rows(db.list_versions(conn))
    cards = []
    for key, config in BILL_TYPES.items():
        if key == "fuel":
            readiness = [
                {"label": "Profile", "value": "route defaults loaded", "state": "ready"},
                {"label": "Rows", "value": "built on open", "state": "ready"},
                {"label": "Prices", "value": "fetched during generation", "state": "ready"},
            ]
        else:
            payload = enrich_payload_assets(key, load_or_sample_payload(uid, key, month))
            readiness = readiness_items(key, payload, profile)
        cards.append({"key": key, "config": config, "readiness": readiness})
    month_versions = [row for row in versions if row["month"] == month]
    return template(
        "pages/dashboard.html",
        request,
        profile=profile,
        bill_types=BILL_TYPES,
        bill_cards=cards,
        versions=latest_versions(month_versions)[:8],
        month=month,
        month_display=month_label(month),
        is_future_month=parse_month(month) > date.today().replace(day=1),
    )


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, setup: str = "0") -> HTMLResponse:
    uid = user_id()
    with db.connect() as conn:
        profile = db.get_profile(conn, uid)
    missing = db.missing_profile_fields(profile)
    return template(
        "pages/profile.html",
        request,
        profile=profile,
        onboarding=setup == "1" or bool(missing),
        missing_fields=missing,
        error="",
    )


@app.post("/profile")
async def save_profile(request: Request):
    uid = user_id()
    form_data = await request.form()
    form = {key: str(value).strip() for key, value in form_data.items() if isinstance(value, str)}
    
    upload = form_data.get("driver_signature_upload")
    if getattr(upload, "filename", None):
        driver_name = form.get("default_driver_name") or "driver"
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", driver_name).strip("-").lower()
        suffix = Path(upload.filename).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            path = ASSETS_DIR / f"signature-{safe_name}{suffix}"
            content = await upload.read()
            path.write_bytes(content)

    missing = db.missing_profile_fields(form)
    if missing:
        return template(
            "pages/profile.html",
            request,
            profile=form,
            onboarding=True,
            missing_fields=missing,
            error="Complete all required profile fields before using the generators.",
        )
    with db.connect() as conn:
        db.save_profile(conn, uid, form)
    return RedirectResponse("/", status_code=303)


@app.get("/generate/{bill_type}", response_class=HTMLResponse)
def generate_page(request: Request, bill_type: str, month: str = "") -> HTMLResponse:
    month = selected_month(month)
    uid = user_id()
    if bill_type not in BILL_TYPES:
        raise HTTPException(status_code=404, detail="unknown bill type")
    with db.connect() as conn:
        profile = db.get_profile(conn, uid)
    payload = enrich_payload_assets(bill_type, load_or_sample_payload(uid, bill_type, month))
    return template(
        "pages/generate.html",
        request,
        bill_type=bill_type,
        config=BILL_TYPES[bill_type],
        month=month,
        payload=payload,
        assets=asset_options(uid),
        readiness=readiness_items(bill_type, payload, profile),
        preview_url=f"/preview/{bill_type}?month={month}",
        preview_frame_url=f"/preview/{bill_type}?month={month}&frame=1",
    )


@app.get("/preview/{bill_type}", response_class=HTMLResponse)
def preview_page(request: Request, bill_type: str, month: str = "", frame: str = "0") -> HTMLResponse:
    month = selected_month(month)
    uid = user_id()
    if bill_type not in BILL_TYPES:
        raise HTTPException(status_code=404, detail="unknown bill type")
    html, _ = preview_html(uid, bill_type, month)
    if frame == "1":
        html = frame_preview_html(html, bill_type)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.post("/generate/internet")
async def generate_internet(request: Request):
    uid = user_id()
    form = await request.form()
    month = str(form["month"])
    payload = InternetBill(
        provider_name=str(form["provider_name"]),
        provider_logo_text=str(form.get("provider_logo_text") or ""),
        provider_address=str(form["provider_address"]),
        customer_name=str(form["customer_name"]),
        customer_address=str(form["customer_address"]),
        account_number=str(form["account_number"]),
        invoice_number=str(form["invoice_number"]),
        bill_date=date.fromisoformat(str(form["bill_date"])),
        amount=Decimal(str(form["amount"])),
        plan_speed=str(form["plan_speed"]),
        plan_package=str(form["plan_package"]),
        plan_validity=str(form["plan_validity"]),
        discount=Decimal(str(form["discount"])),
        payment_method=str(form["payment_method"]),
        provider_logo_path=str(form.get("provider_logo_path") or "") or None,
        tax=TaxFields(
            taxable_amount=Decimal(str(form["taxable_amount"])),
            cgst_rate=Decimal(str(form["cgst_rate"])),
            sgst_rate=Decimal(str(form["sgst_rate"])),
            payments_received=Decimal(str(form["payments_received"])),
        ),
    ).model_dump(mode="json")
    if form.get("action") == "preview":
        html, _ = preview_html(uid, "internet", month, payload)
        if form.get("frame"):
            html = frame_preview_html(html, "internet")
        return HTMLResponse(html)
    result = generate_bill(uid, "internet", month, payload)
    return RedirectResponse(f"/documents?month={month}&generated={result['version_id']}", status_code=303)


@app.post("/generate/driver")
async def generate_driver(request: Request):
    uid = user_id()
    form = await request.form()
    month = str(form["month"])
    uploaded_stamp_id = await save_uploaded_asset(uid, form.get("revenue_stamp_upload"), "revenue_stamp")
    uploaded_signature_id = await save_uploaded_asset(uid, form.get("signature_upload"), "signature")
    payload = DriverSalaryBill(
        employee_name=str(form["employee_name"]),
        driver_name=str(form["driver_name"]),
        vehicle_number=str(form["vehicle_number"]),
        salary_amount=Decimal(str(form["salary_amount"])),
        month=month,
        receipt_date=date.fromisoformat(str(form["receipt_date"])),
        template_style=str(form.get("template_style") or "1"),
        revenue_stamp_asset_id=uploaded_stamp_id or selected_asset_id(form, "revenue_stamp_asset_id"),
        signature_asset_id=uploaded_signature_id or selected_asset_id(form, "signature_asset_id"),
        revenue_stamp_path=str(form.get("revenue_stamp_path") or "") or None,
        signature_path=str(form.get("signature_path") or "") or None,
        stamp_x=form_float(form, "stamp_x", 78),
        stamp_y=form_float(form, "stamp_y", 0),
        stamp_scale=form_float(form, "stamp_scale", 1),
        signature_x=form_float(form, "signature_x", -390),
        signature_y=form_float(form, "signature_y", -88),
        signature_scale=form_float(form, "signature_scale", 1),
        signature_rotation=form_float(form, "signature_rotation", -16),
    ).model_dump(mode="json")
    if form.get("action") == "preview":
        html, _ = preview_html(uid, "driver", month, payload)
        if form.get("frame"):
            html = frame_preview_html(html, "driver")
        return HTMLResponse(html)
    result = generate_bill(uid, "driver", month, payload)
    return RedirectResponse(f"/documents?month={month}&generated={result['version_id']}", status_code=303)


@app.post("/generate/book")
async def generate_book(request: Request):
    uid = user_id()
    form = await request.form()
    month = str(form["month"])
    payload = BookBill(
        lookup_keyword=str(form.get("lookup_keyword") or "") or None,
        receipt_number=str(form["receipt_number"]),
        receipt_date=date.fromisoformat(str(form["receipt_date"])),
        customer_name=str(form["customer_name"]),
        store_name=str(form["store_name"]),
        store_address=str(form["store_address"]),
        book_name=str(form["book_name"]),
        author=str(form["author"]),
        publisher=str(form["publisher"]),
        description=str(form["description"]),
        quantity=int(str(form["quantity"])),
        price=Decimal(str(form["price"])),
        payment_method=str(form["payment_method"]),
        price_confirmed=bool(form.get("price_confirmed")),
    ).model_dump(mode="json")
    if form.get("action") == "preview":
        html, _ = preview_html(uid, "book", month, payload)
        if form.get("frame"):
            html = frame_preview_html(html, "book")
        return HTMLResponse(html)
    result = generate_bill(uid, "book", month, payload)
    return RedirectResponse(f"/documents?month={month}&generated={result['version_id']}", status_code=303)


@app.post("/generate/fuel")
async def generate_fuel(request: Request):
    uid = user_id()
    form = await request.form()
    month = str(form["month"])
    with db.connect() as conn:
        profile = db.get_profile(conn, uid)
    profile["_receipt_template"] = str(form.get("receipt_template") or "1")
    if form.get("manual_fuel_rows"):
        payload = parse_fuel_items(manual_fuel_items_from_form(form), profile, month)
    elif form.get("manual_fuel_csv"):
        payload = parse_fuel_csv(str(form["fuel_csv"]), profile, month)
    else:
        payload = sample_payload("fuel", month, profile)
        payload["receipt_template"] = profile["_receipt_template"]
    if form.get("action") == "preview":
        html, _ = preview_html(uid, "fuel", month, payload)
        if form.get("frame"):
            html = frame_preview_html(html, "fuel")
        return HTMLResponse(html)
    manual_override_fields = {"rows"} if form.get("manual_fuel_rows") or form.get("manual_fuel_csv") else set()
    result = generate_bill(uid, "fuel", month, payload, manual_override_fields=manual_override_fields)
    return RedirectResponse(f"/documents?month={month}&generated={result['version_id']}", status_code=303)


@app.get("/documents", response_class=HTMLResponse)
def documents(request: Request, month: str = "", bill_type: str = "", latest: str = "1") -> HTMLResponse:
    user_id()
    with db.connect() as conn:
        all_versions = version_view_rows(db.list_versions(conn))
    months = sorted({row["month"] for row in all_versions}, reverse=True)
    selected_month = month or (months[0] if months else "")
    latest_only = latest != "0"
    versions = filter_versions(all_versions, selected_month, bill_type, latest_only)
    bundle = None
    if selected_month:
        bundle_path = OUTPUT_DIR / output_month_dir(selected_month) / f"reimbursement_bundle_{month_label(selected_month).replace(' ', '_')}.zip"
        if bundle_path.exists():
            bundle = versioned_output_url(bundle_path)
    return template(
        "pages/documents.html",
        request,
        versions=versions,
        months=months,
        selected_month=selected_month,
        selected_type=bill_type,
        latest_only=latest_only,
        bundle_url=bundle,
        bill_types=BILL_TYPES,
    )


@app.get("/bundle/{month}")
def bundle_month(month: str):
    month = selected_month(month)
    uid = user_id()
    generate_bill(uid, "all", month)
    path = export_bundle(month)
    return RedirectResponse(versioned_output_url(path), status_code=303)


@app.get("/bundle")
def bundle_current(month: str = ""):
    month = selected_month(month)
    uid = user_id()
    generate_bill(uid, "all", month)
    path = export_bundle(month)
    return RedirectResponse(versioned_output_url(path), status_code=303)


@app.post("/bundle")
async def build_bundle(request: Request):
    form = await request.form()
    month = selected_month(str(form.get("month") or ""))
    uid = user_id()
    generate_bill(uid, "all", month)
    path = export_bundle(month)
    return RedirectResponse(versioned_output_url(path), status_code=303)


@app.get("/book-lookup", response_class=HTMLResponse)
async def book_lookup(request: Request, q: str = "") -> HTMLResponse:
    results = await search_openlibrary(q) if q else []
    return template("pages/book_lookup.html", request, q=q, results=results)
