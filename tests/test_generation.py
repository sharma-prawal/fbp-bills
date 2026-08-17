from pathlib import Path
from zipfile import ZipFile

from pypdf import PdfReader

from app import db
from app.distribution import build_sanitized_distribution
from app.renderer import html_to_pdf
from app.services import field_audit, load_or_sample_payload


def test_pdf_generation_smoke(tmp_path: Path) -> None:
    pdf = html_to_pdf("<html><body><h1>Smoke</h1><p>PDF generation works.</p></body></html>", tmp_path / "smoke.pdf")
    assert pdf.exists()
    assert len(PdfReader(str(pdf)).pages) == 1


def test_version_history_creation(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    db.seed_demo_data(db_path)
    with db.connect(db_path) as conn:
        user_id = db.get_or_create_user(conn)
        instance_id = db.create_instance(conn, user_id, "internet", "2026-06")
        v1 = db.add_version(conn, instance_id, {"invoice_number": "IN1"}, {"invoice_number": {"source": "manual"}}, "a.html", "a.pdf")
        v2 = db.add_version(conn, instance_id, {"invoice_number": "IN2"}, {"invoice_number": {"source": "manual"}}, "b.html", "b.pdf")
        row = conn.execute("SELECT current_version_id FROM bill_instances WHERE id = ?", (instance_id,)).fetchone()
    assert v2 > v1
    assert row["current_version_id"] == v2


def test_fuel_price_lookup_uses_latest_on_or_before_date(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO fuel_price_sources(city, price_date, price_per_litre, source_type, source_url, note, created_at)
            VALUES ('Delhi', '2026-06-01', '102.12', 'manual', 'manual:test', 'test source', ?)
            """,
            (db.now_iso(),),
        )
        row = db.lookup_fuel_price(conn, "delhi", "2026-06-15")
    assert row["price_per_litre"] == "102.12"


def test_profile_values_replace_legacy_saved_snapshots(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    db.seed_demo_data(db_path)
    cases = [
        ("internet", "provider_name", "Legacy ISP", "Current ISP"),
        ("driver", "salary_amount", "18000", "22000"),
        ("book", "price", "5193", "5199"),
        ("fuel", "employee_name", "Legacy Employee", "Current Employee"),
    ]

    with db.connect(db_path) as conn:
        user_id = db.get_or_create_user(conn)
        profile = db.get_profile(conn, user_id)
        profile.update(
            {
                "default_internet_provider": "Current ISP",
                "default_driver_salary": "22000",
                "default_book_price": "5199",
                "employee_name": "Current Employee",
            }
        )
        db.save_profile(conn, user_id, profile)
        for bill_type, field, stale_value, _ in cases:
            instance_id = db.create_instance(conn, user_id, bill_type, "2026-06")
            source = {field: stale_value}
            if bill_type == "fuel":
                source["rows"] = [{"receipt_number": "MANUAL-1"}]
            db.add_version(
                conn,
                instance_id,
                source,
                {
                    field: {"source": "manual_or_sample"},
                    "rows": {"source": "manual_override", "row_count": 1},
                },
                "a.html",
                "a.pdf",
            )

    for bill_type, field, _, expected in cases:
        payload = load_or_sample_payload(user_id, bill_type, "2026-06", db_path=db_path)
        assert str(payload[field]) == expected


def test_explicit_manual_override_stays_above_profile(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    db.seed_demo_data(db_path)
    with db.connect(db_path) as conn:
        user_id = db.get_or_create_user(conn)
        profile = db.get_profile(conn, user_id)
        profile["default_book_price"] = "5199"
        db.save_profile(conn, user_id, profile)
        instance_id = db.create_instance(conn, user_id, "book", "2026-06")
        db.add_version(
            conn,
            instance_id,
            {"price": "5299"},
            {"price": {"source": "manual_override"}},
            "a.html",
            "a.pdf",
        )

    payload = load_or_sample_payload(user_id, "book", "2026-06", db_path=db_path)
    assert payload["price"] == "5299"


def test_field_audit_marks_profile_and_manual_values() -> None:
    profile = {
        "employee_name": "Sample Employee",
        "default_book_lookup_keyword": "",
        "default_book_receipt_date": "2026-06-14",
        "default_book_store_name": "Sample Books",
        "default_book_store_address": "Store address",
        "default_book_quantity": "1",
        "default_book_price": "5199",
        "default_book_payment_method": "Online",
    }
    payload = {
        "customer_name": "Sample Employee",
        "price": "5299",
        "book_name": "Generated Book",
    }

    audit = field_audit("book", "2026-06", payload, profile)

    assert audit["customer_name"]["source"] == "profile_default"
    assert audit["price"]["source"] == "manual_override"
    assert audit["book_name"]["source"] == "user_input_or_generated"


def test_fresh_install_starts_with_empty_required_profile(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.sqlite3"
    db.initialize_installation(db_path)

    with db.connect(db_path) as conn:
        user_id = db.get_or_create_user(conn)
        profile = db.get_profile(conn, user_id)

    assert profile["employee_name"] == ""
    assert profile["vehicle_number"] == ""
    assert not db.profile_is_complete(profile)
    assert "Name" in db.missing_profile_fields(profile)


def test_existing_profile_is_not_overwritten_by_initialization(tmp_path: Path) -> None:
    db_path = tmp_path / "existing.sqlite3"
    db.initialize_installation(db_path)
    with db.connect(db_path) as conn:
        user_id = db.get_or_create_user(conn)
        profile = db.get_profile(conn, user_id)
        profile["employee_name"] = "Existing User"
        profile["vehicle_number"] = "TEST-123"
        db.save_profile(conn, user_id, profile)

    db.initialize_installation(db_path)

    with db.connect(db_path) as conn:
        profile = db.get_profile(conn, user_id)
    assert profile["employee_name"] == "Existing User"
    assert profile["vehicle_number"] == "TEST-123"


def test_sanitized_distribution_excludes_private_directories(tmp_path: Path) -> None:
    archive_path = build_sanitized_distribution(tmp_path / "share.zip")

    with ZipFile(archive_path) as archive:
        names = archive.namelist()

    assert "assets/README.txt" in names
    assert "data/.gitkeep" in names
    assert "output/.gitkeep" in names
    assert not any(name.startswith("original-reference-docs/") for name in names)
    assert not any(name.endswith((".sqlite3", ".pdf")) for name in names)
    assert not any(name.endswith((".png", ".webp")) for name in names if not name.startswith("assets/"))
