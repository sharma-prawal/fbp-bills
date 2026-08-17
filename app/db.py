from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.config import DATA_DIR, DB_PATH
from app.registry import BILL_TYPES

PROFILE_DEFAULTS = {
    "employee_name": "",
    "employee_code": "",
    "address": "",
    "phone": "",
    "mobile_number": "",
    "email": "",
    "vehicle_number": "",
    "project_name": "",
    "default_from_city": "",
    "default_to_city": "",
    "from_city_receipt_fuel_city": "",
    "from_city_pump_name": "",
    "from_city_pump_address": "",
    "from_city_pump_phone": "",
    "to_city_receipt_fuel_city": "",
    "to_city_pump_name": "",
    "to_city_pump_address": "",
    "to_city_pump_phone": "",
    "default_internet_provider": "",
    "default_internet_provider_address": "",
    "internet_account_number": "",
    "default_internet_bill_date": "",
    "default_internet_base_amount": "",
    "default_driver_name": "",
    "default_driver_salary": "",
    "default_driver_receipt_date": "",
    "driver_stamp_x": "78",
    "driver_stamp_y": "0",
    "driver_stamp_scale": "1",
    "driver_signature_x": "-390",
    "driver_signature_y": "-88",
    "driver_signature_scale": "1",
    "driver_signature_rotation": "-16",
    "default_book_lookup_keyword": "",
    "default_book_receipt_date": "",
    "default_book_store_name": "",
    "default_book_store_address": "",
    "default_book_payment_method": "Online",
    "default_book_quantity": "1",
    "default_book_price": "",
    "default_fuel_vendor": "",
    "default_fuel_receipt_template": "1",
}

REQUIRED_PROFILE_FIELDS = {
    "employee_name": "Name",
    "employee_code": "Employee code",
    "address": "Address",
    "mobile_number": "Mobile number",
    "vehicle_number": "Vehicle number",
    "project_name": "Project name",
    "default_from_city": "Travel from city",
    "default_to_city": "Travel to city",
    "from_city_receipt_fuel_city": "From-side fuel city",
    "from_city_pump_name": "From-side petrol pump",
    "from_city_pump_address": "From-side pump address",
    "from_city_pump_phone": "From-side pump phone",
    "to_city_receipt_fuel_city": "To-side fuel city",
    "to_city_pump_name": "To-side petrol pump",
    "to_city_pump_address": "To-side pump address",
    "to_city_pump_phone": "To-side pump phone",
    "default_internet_provider": "Internet provider",
    "default_internet_provider_address": "Internet provider address",
    "internet_account_number": "Internet account number",
    "default_internet_bill_date": "Internet bill date",
    "default_internet_base_amount": "Internet base amount (before tax)",
    "default_driver_name": "Driver name",
    "default_driver_salary": "Driver salary",
    "default_driver_receipt_date": "Driver receipt date",
    "default_book_receipt_date": "Book receipt date",
    "default_book_store_name": "Book store name",
    "default_book_store_address": "Book store address",
    "default_book_payment_method": "Book payment method",
    "default_book_quantity": "Book quantity",
    "default_book_price": "Book price",
}


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                data_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bill_types (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                config_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bill_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                bill_type TEXT NOT NULL REFERENCES bill_types(key),
                month TEXT NOT NULL,
                current_version_id INTEGER,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bill_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_instance_id INTEGER NOT NULL REFERENCES bill_instances(id),
                version_number INTEGER NOT NULL,
                source_json TEXT NOT NULL,
                field_audit_json TEXT NOT NULL,
                html_path TEXT,
                pdf_path TEXT,
                extra_outputs_json TEXT NOT NULL DEFAULT '{}',
                generated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fuel_price_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT NOT NULL,
                price_date TEXT NOT NULL,
                price_per_litre TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_url TEXT,
                note TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fuel_log_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_instance_id INTEGER REFERENCES bill_instances(id),
                row_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                asset_type TEXT NOT NULL,
                label TEXT NOT NULL,
                path TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        # Collapse any pre-existing duplicate price rows before enforcing uniqueness,
        # then prevent future duplicates (and the SELECT-then-INSERT race in the
        # price fetch paths) with a unique index.
        conn.execute(
            """
            DELETE FROM fuel_price_sources
            WHERE id NOT IN (
                SELECT MIN(id) FROM fuel_price_sources
                GROUP BY city, price_date, source_type
            )
            """
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_fuel_price_sources_unique "
            "ON fuel_price_sources(city, price_date, source_type)"
        )
        for config in BILL_TYPES.values():
            conn.execute(
                "INSERT OR REPLACE INTO bill_types(key, name, config_json) VALUES (?, ?, ?)",
                (config.key, config.name, json.dumps(config.to_json(), indent=2)),
            )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_dump(data: Any) -> str:
    return json.dumps(data, default=str, indent=2)


def get_or_create_user(conn: sqlite3.Connection, name: str = "Local User", email: str | None = None) -> int:
    row = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO users(name, email, created_at) VALUES (?, ?, ?)",
        (name, email, now_iso()),
    )
    return int(cur.lastrowid)


def save_profile(conn: sqlite3.Connection, user_id: int, profile: dict[str, Any]) -> int:
    existing = conn.execute("SELECT id FROM profiles WHERE user_id = ? ORDER BY id LIMIT 1", (user_id,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE profiles SET data_json = ?, updated_at = ? WHERE id = ?",
            (json_dump(profile), now_iso(), existing["id"]),
        )
        return int(existing["id"])
    cur = conn.execute(
        "INSERT INTO profiles(user_id, data_json, updated_at) VALUES (?, ?, ?)",
        (user_id, json_dump(profile), now_iso()),
    )
    return int(cur.lastrowid)


def seed_profile_defaults(conn: sqlite3.Connection, user_id: int, defaults: dict[str, Any]) -> int:
    existing = conn.execute("SELECT id, data_json FROM profiles WHERE user_id = ? ORDER BY id LIMIT 1", (user_id,)).fetchone()
    if existing:
        current = json.loads(existing["data_json"])
        changed = False
        for key, value in defaults.items():
            if key not in current:
                current[key] = value
                changed = True
        if current.get("default_book_lookup_keyword") == "Open Magazine":
            current["default_book_lookup_keyword"] = ""
            changed = True
        if "mobile_number" not in current and current.get("phone"):
            current["mobile_number"] = current["phone"]
            changed = True
        if str(current.get("driver_signature_y", "")).strip() in {"16", "-28"}:
            current["driver_signature_y"] = "-88"
            changed = True
        if changed:
            conn.execute(
                "UPDATE profiles SET data_json = ?, updated_at = ? WHERE id = ?",
                (json_dump(current), now_iso(), existing["id"]),
            )
        return int(existing["id"])
    return save_profile(conn, user_id, defaults)


def get_profile(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT data_json FROM profiles WHERE user_id = ? ORDER BY id LIMIT 1", (user_id,)).fetchone()
    if not row:
        raise LookupError("profile not found")
    return json.loads(row["data_json"])


def missing_profile_fields(profile: dict[str, Any]) -> list[str]:
    return [
        label
        for key, label in REQUIRED_PROFILE_FIELDS.items()
        if not str(profile.get(key) or "").strip()
    ]


def profile_is_complete(profile: dict[str, Any]) -> bool:
    return not missing_profile_fields(profile)


def find_instance(conn: sqlite3.Connection, user_id: int, bill_type: str, month: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM bill_instances WHERE user_id = ? AND bill_type = ? AND month = ? ORDER BY id DESC LIMIT 1",
        (user_id, bill_type, month),
    ).fetchone()


def create_instance(conn: sqlite3.Connection, user_id: int, bill_type: str, month: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO bill_instances(user_id, bill_type, month, status, created_at, updated_at)
        VALUES (?, ?, ?, 'draft', ?, ?)
        """,
        (user_id, bill_type, month, now_iso(), now_iso()),
    )
    return int(cur.lastrowid)


def add_version(
    conn: sqlite3.Connection,
    instance_id: int,
    source: dict[str, Any],
    field_audit: dict[str, Any],
    html_path: str | None,
    pdf_path: str | None,
    extra_outputs: dict[str, Any] | None = None,
) -> int:
    current = conn.execute(
        "SELECT COALESCE(MAX(version_number), 0) AS n FROM bill_versions WHERE bill_instance_id = ?",
        (instance_id,),
    ).fetchone()
    version_number = int(current["n"]) + 1
    cur = conn.execute(
        """
        INSERT INTO bill_versions(
            bill_instance_id, version_number, source_json, field_audit_json,
            html_path, pdf_path, extra_outputs_json, generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            instance_id,
            version_number,
            json_dump(source),
            json_dump(field_audit),
            html_path,
            pdf_path,
            json_dump(extra_outputs or {}),
            now_iso(),
        ),
    )
    version_id = int(cur.lastrowid)
    conn.execute(
        "UPDATE bill_instances SET current_version_id = ?, status = 'generated', updated_at = ? WHERE id = ?",
        (version_id, now_iso(), instance_id),
    )
    return version_id


def list_versions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT bi.id AS instance_id, bi.bill_type, bi.month, bv.*
        FROM bill_versions bv
        JOIN bill_instances bi ON bi.id = bv.bill_instance_id
        ORDER BY bv.generated_at DESC
        """
    ).fetchall()


def create_asset(conn: sqlite3.Connection, user_id: int, asset_type: str, label: str, path: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO assets(user_id, asset_type, label, path, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, asset_type, label, path, now_iso()),
    )
    return int(cur.lastrowid)


def list_assets(conn: sqlite3.Connection, user_id: int, asset_type: str | None = None) -> list[sqlite3.Row]:
    if asset_type:
        return conn.execute(
            "SELECT * FROM assets WHERE user_id = ? AND asset_type = ? ORDER BY created_at DESC",
            (user_id, asset_type),
        ).fetchall()
    return conn.execute("SELECT * FROM assets WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()


def get_asset(conn: sqlite3.Connection, asset_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()


def lookup_fuel_price(conn: sqlite3.Connection, city: str, price_date: str) -> sqlite3.Row | None:
    row = conn.execute(
        """
        SELECT *
        FROM fuel_price_sources
        WHERE lower(city) = lower(?)
          AND price_date <= ?
          AND substr(price_date, 1, 7) = substr(?, 1, 7)
        ORDER BY price_date DESC, id DESC
        LIMIT 1
        """,
        (city.strip(), price_date, price_date),
    ).fetchone()
    if row:
        return row
    # No rate published on or before this date, but one may exist later in the
    # same month (e.g. an approximate rate stored for an early-month date that
    # predates the source's rolling history). Reuse the nearest available rather
    # than re-fetching for every generation.
    return conn.execute(
        """
        SELECT *
        FROM fuel_price_sources
        WHERE lower(city) = lower(?)
          AND substr(price_date, 1, 7) = substr(?, 1, 7)
        ORDER BY price_date ASC, id DESC
        LIMIT 1
        """,
        (city.strip(), price_date),
    ).fetchone()


def initialize_installation(db_path: Path = DB_PATH) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        user_id = get_or_create_user(conn)
        seed_profile_defaults(conn, user_id, PROFILE_DEFAULTS)
        profile = get_profile(conn, user_id)
        if not str(profile.get("default_internet_provider_address") or "").strip():
            row = conn.execute(
                """
                SELECT bv.source_json
                FROM bill_versions bv
                JOIN bill_instances bi ON bi.id = bv.bill_instance_id
                WHERE bi.user_id = ? AND bi.bill_type = 'internet'
                ORDER BY bv.generated_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            if row:
                source = json.loads(row["source_json"])
                provider_address = str(source.get("provider_address") or "").strip()
                if provider_address:
                    profile["default_internet_provider_address"] = provider_address
                    save_profile(conn, user_id, profile)


def seed_demo_data(db_path: Path = DB_PATH) -> None:
    """Backward-compatible alias; fresh installs intentionally contain no personal data."""
    initialize_installation(db_path)
