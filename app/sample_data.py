from __future__ import annotations

import calendar
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app import db
from app.assets import internet_logo_for, pump_logo_for, revenue_stamp_path, signature_for
from app.book_lookup import dynamic_book
from app.fuel_prices import effective_lookup_date, fetch_goodreturns_petrol_price
from app.models import BookBill, DriverSalaryBill, FuelBill, FuelLogRow, InternetBill, TaxFields


DEFAULT_FUEL_PUMPS = {
    "from": {"vendor": "", "address": "", "phone": ""},
    "to": {"vendor": "", "address": "", "phone": ""},
}

CITY_COORDINATES = {
    "agra": (27.1767, 78.0081),
    "ajmer": (26.4499, 74.6399),
    "alwar": (27.5529, 76.6346),
    "bengaluru": (12.9716, 77.5946),
    "bhopal": (23.2599, 77.4126),
    "chandigarh": (30.7333, 76.7794),
    "dehradun": (30.3165, 78.0322),
    "delhi": (28.6139, 77.2090),
    "faridabad": (28.4089, 77.3178),
    "ghaziabad": (28.6692, 77.4538),
    "gurgaon": (28.4595, 77.0266),
    "gurugram": (28.4595, 77.0266),
    "jaipur": (26.9124, 75.7873),
    "jodhpur": (26.2389, 73.0243),
    "kanpur": (26.4499, 80.3319),
    "kota": (25.2138, 75.8648),
    "lucknow": (26.8467, 80.9462),
    "meerut": (28.9845, 77.7064),
    "new delhi": (28.6139, 77.2090),
    "noida": (28.5355, 77.3910),
    "udaipur": (24.5854, 73.7125),
}


@dataclass(frozen=True)
class TripItinerary:
    outbound_departure: datetime
    outbound_arrival: datetime
    return_departure: datetime
    return_arrival: datetime


def seeded_rng(*parts: object) -> random.Random:
    seed = "|".join(str(part) for part in parts)
    return random.Random(seed)


def receipt_number(rng: random.Random, used: set[str]) -> str:
    while True:
        value = str(rng.randrange(100000, 999999))
        if value not in used:
            used.add(value)
            return value


def city_key(city: str) -> str:
    return " ".join(city.lower().replace("-", " ").split())


def route_distance_km(from_city: str, to_city: str) -> int:
    from_coords = CITY_COORDINATES.get(city_key(from_city))
    to_coords = CITY_COORDINATES.get(city_key(to_city))
    if not from_coords or not to_coords:
        return 560
    lat1, lon1 = from_coords
    lat2, lon2 = to_coords
    earth_radius_km = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    haversine = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    straight_line_km = 2 * earth_radius_km * math.asin(math.sqrt(haversine))
    return max(1, round(straight_line_km * 1.12))


def route_leg_km(base_distance_km: int, week_index: int, rng: random.Random, return_leg: bool = False) -> int:
    route_variation = week_index * 6 + rng.randrange(-15, 16)
    return max(1, base_distance_km + route_variation - (26 if return_leg else 0))


def travel_duration(distance_km: int, rng: random.Random) -> timedelta:
    average_speed_kmph = Decimal(rng.randrange(64, 70))
    hours = Decimal(distance_km) / average_speed_kmph
    minutes = int((hours * Decimal("60")).quantize(Decimal("1")))
    return timedelta(minutes=minutes)


def trip_itinerary(
    outbound_date: date,
    return_date: date,
    outbound_distance_km: int,
    return_distance_km: int,
    rng: random.Random,
) -> TripItinerary:
    outbound_departure = datetime.combine(outbound_date, time(8, 0)) + timedelta(minutes=rng.randrange(0, 61))
    outbound_duration = travel_duration(outbound_distance_km, rng)
    outbound_arrival = outbound_departure + outbound_duration
    return_departure = datetime.combine(return_date, time(8, 0)) + timedelta(minutes=rng.randrange(0, 61))
    return_duration = travel_duration(return_distance_km, rng)
    return_arrival = return_departure + return_duration
    return TripItinerary(
        outbound_departure=outbound_departure,
        outbound_arrival=outbound_arrival,
        return_departure=return_departure,
        return_arrival=return_arrival,
    )

def consecutive_working_day_pairs(month: str, pair_count: int = 3) -> list[tuple[date, date]]:
    year, month_num = [int(part) for part in month.split("-")]
    _, days_in_month = calendar.monthrange(year, month_num)
    pairs: list[tuple[date, date]] = []
    day = 1
    while day < days_in_month and len(pairs) < pair_count:
        first = date(year, month_num, day)
        second = date(year, month_num, day + 1)
        if first.weekday() < 5 and second.weekday() < 5 and first.isocalendar().week == second.isocalendar().week:
            pairs.append((first, second))
            day += 7
        else:
            day += 1
    return pairs


def profile_decimal(profile: dict, key: str, fallback: str) -> str:
    return str(profile.get(key) or fallback)


def profile_date(profile: dict, key: str, fallback: date) -> date:
    raw = str(profile.get(key) or "").strip()
    if not raw:
        return fallback
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return fallback


def profile_date_for_month(profile: dict, key: str, month: str, fallback_day: int) -> date:
    year, month_num = [int(part) for part in month.split("-")]
    raw = str(profile.get(key) or "").strip()
    day = fallback_day
    if raw:
        try:
            day = date.fromisoformat(raw).day
        except ValueError:
            pass
    day = min(day, calendar.monthrange(year, month_num)[1])
    return date(year, month_num, day)


def fuel_price_for(city: str, row_date: date) -> tuple[str, str]:
    today = date.today()
    lookup_date = effective_lookup_date(row_date, today)
    future_note = (
        f"future travel date {row_date.isoformat()}; latest available price as of {today.isoformat()}"
        if row_date > today
        else ""
    )
    with db.connect() as conn:
        cached = db.lookup_fuel_price(conn, city, lookup_date.isoformat())
    if cached:
        source_parts = [cached["source_type"], cached["price_date"]]
        if cached["source_url"]:
            source_parts.append(cached["source_url"])
        if cached["note"]:
            source_parts.append(cached["note"])
        if future_note:
            source_parts.append(future_note)
        return str(cached["price_per_litre"]), ": ".join(source_parts)

    # Fetch outside of any open connection so a slow network call never holds a
    # SQLite handle. The unique index makes the insert idempotent under races.
    try:
        fetched = fetch_goodreturns_petrol_price(city, lookup_date)
    except Exception as exc:
        raise ValueError(
            f"Could not fetch a verified petrol price for {city} on or before {lookup_date.isoformat()}"
        ) from exc

    note_parts = [
        f"Fetched for requested date {row_date.isoformat()}" if row_date <= lookup_date else future_note
    ]
    if fetched.approximate and fetched.note:
        note_parts.append(fetched.note)
    note = "; ".join(part for part in note_parts if part)
    with db.connect() as conn:
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
                note,
                db.now_iso(),
            ),
        )

    source_parts = [f"{fetched.source_name}: {fetched.effective_date.isoformat()}: {fetched.source_url}"]
    if future_note:
        source_parts.append(future_note)
    if fetched.approximate and fetched.note:
        source_parts.append(fetched.note)
    return str(fetched.price_per_litre), ": ".join(source_parts)


def litres(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def receipt_time(value: datetime) -> str:
    return value.time().replace(second=0, microsecond=0).isoformat(timespec="minutes")


def profile_text(profile: dict, key: str, fallback: str) -> str:
    value = str(profile.get(key) or "").strip()
    return value or fallback


def profile_float(profile: dict, key: str, fallback: float) -> float:
    raw = str(profile.get(key) or "").strip()
    if not raw:
        return fallback
    try:
        return float(raw)
    except ValueError:
        return fallback


def profile_backed_values(bill_type: str, month: str, profile: dict) -> dict:
    if bill_type == "internet":
        provider = profile_text(profile, "default_internet_provider", "")
        base_taxable = float(profile_decimal(profile, "default_internet_base_amount", "3999"))
        cgst = round(base_taxable * 0.09, 2)
        sgst = round(base_taxable * 0.09, 2)
        total = base_taxable + cgst + sgst
        return {
            "provider_name": provider,
            "provider_logo_path": internet_logo_for(provider),
            "provider_address": profile_text(profile, "default_internet_provider_address", ""),
            "customer_name": profile_text(profile, "employee_name", ""),
            "customer_address": profile_text(profile, "address", ""),
            "account_number": profile_text(profile, "internet_account_number", ""),
            "bill_date": profile_date_for_month(profile, "default_internet_bill_date", month, 3).isoformat(),
            "amount": f"{total:.2f}",
            "tax": {
                "taxable_amount": f"{base_taxable:.2f}",
                "cgst_rate": "9",
                "sgst_rate": "9",
                "payments_received": f"{total:.2f}"
            }
        }
    if bill_type == "driver":
        driver_name = profile_text(profile, "default_driver_name", "")
        return {
            "employee_name": profile_text(profile, "employee_name", ""),
            "driver_name": driver_name,
            "vehicle_number": profile_text(profile, "vehicle_number", ""),
            "salary_amount": profile_decimal(profile, "default_driver_salary", "0"),
            "receipt_date": profile_date_for_month(profile, "default_driver_receipt_date", month, 12).isoformat(),
            "revenue_stamp_path": revenue_stamp_path(),
            "signature_path": signature_for(driver_name),
            "stamp_x": profile_float(profile, "driver_stamp_x", 78),
            "stamp_y": profile_float(profile, "driver_stamp_y", 0),
            "stamp_scale": profile_float(profile, "driver_stamp_scale", 1),
            "signature_x": profile_float(profile, "driver_signature_x", -390),
            "signature_y": profile_float(profile, "driver_signature_y", -88),
            "signature_scale": profile_float(profile, "driver_signature_scale", 1),
            "signature_rotation": profile_float(profile, "driver_signature_rotation", -16),
        }
    if bill_type == "book":
        return {
            "lookup_keyword": profile.get("default_book_lookup_keyword") or None,
            "receipt_date": profile_date_for_month(profile, "default_book_receipt_date", month, 14).isoformat(),
            "customer_name": profile_text(profile, "employee_name", ""),
            "store_name": profile_text(profile, "default_book_store_name", "Book Store"),
            "store_address": profile_text(
                profile,
                "default_book_store_address",
                "SDRD Solutions Pvt Ltd, First floor, Plot No 131, Block D, Sector-12A, Dwarka, New Delhi -110078",
            ),
            "quantity": int(profile_decimal(profile, "default_book_quantity", "1")),
            "price": profile_decimal(profile, "default_book_price", "3999"),
            "payment_method": profile_text(profile, "default_book_payment_method", "Online"),
        }
    if bill_type == "fuel":
        return {
            "employee_name": profile_text(profile, "employee_name", ""),
            "employee_code": profile_text(profile, "employee_code", ""),
            "vehicle_number": profile_text(profile, "vehicle_number", ""),
            "receipt_template": profile_text(profile, "default_fuel_receipt_template", "1"),
        }
    raise ValueError(f"unknown bill type {bill_type}")


def sample_payload(bill_type: str, month: str, profile: dict) -> dict:
    rng = seeded_rng(bill_type, month, profile.get("employee_name", ""))
    if bill_type == "internet":
        base_taxable = float(profile_decimal(profile, "default_internet_base_amount", "3999"))
        cgst = round(base_taxable * 0.09, 2)
        sgst = round(base_taxable * 0.09, 2)
        total = base_taxable + cgst + sgst
        return InternetBill(
            provider_name=profile["default_internet_provider"],
            provider_logo_text="airtel",
            provider_logo_path=internet_logo_for(profile["default_internet_provider"]),
            provider_address=profile_text(profile, "default_internet_provider_address", ""),
            customer_name=profile["employee_name"],
            customer_address=profile["address"],
            account_number=profile["internet_account_number"],
            invoice_number=f"IN{rng.randrange(10000, 99999)}",
            bill_date=profile_date_for_month(profile, "default_internet_bill_date", month, 3),
            amount=f"{total:.2f}",
            plan_speed="1Gbps",
            plan_package="Unlimited",
            plan_validity="Monthly",
            discount="0",
            payment_method="Online",
            tax=TaxFields(taxable_amount=f"{base_taxable:.2f}", cgst_rate="9", sgst_rate="9", payments_received=f"{total:.2f}"),
        ).model_dump(mode="json")
    if bill_type == "driver":
        return DriverSalaryBill(
            employee_name=profile["employee_name"],
            driver_name=profile["default_driver_name"],
            vehicle_number=profile["vehicle_number"],
            salary_amount=profile["default_driver_salary"],
            month=month,
            receipt_date=profile_date_for_month(profile, "default_driver_receipt_date", month, 12),
            template_style="1",
            revenue_stamp_asset_id=None,
            signature_asset_id=None,
            revenue_stamp_path=revenue_stamp_path(),
            signature_path=signature_for(profile["default_driver_name"]),
            stamp_x=profile_float(profile, "driver_stamp_x", 78),
            stamp_y=profile_float(profile, "driver_stamp_y", 0),
            stamp_scale=profile_float(profile, "driver_stamp_scale", 1),
            signature_x=profile_float(profile, "driver_signature_x", -390),
            signature_y=profile_float(profile, "driver_signature_y", -88),
            signature_scale=profile_float(profile, "driver_signature_scale", 1),
            signature_rotation=profile_float(profile, "driver_signature_rotation", -16),
        ).model_dump(mode="json")
    if bill_type == "book":
        # Note: the book itself is chosen in app/services.py via refresh_book_metadata 
        # so it is already randomized across bundle generations. 
        # We just need to ensure the receipt number and fallback price vary.
        book = dynamic_book()
        book_title = book.get("title") or "Monthly Book"
        base_price = float(profile_decimal(profile, "default_book_price", "3999"))
        varied_price = round(base_price, 2)
        return BookBill(
            lookup_keyword=profile.get("default_book_lookup_keyword") or None,
            receipt_number=f"R{rng.randrange(10000, 99999)}",
            receipt_date=profile_date_for_month(profile, "default_book_receipt_date", month, 14),
            customer_name=profile["employee_name"],
            store_name=profile.get("default_book_store_name", "Book Store"),
            store_address=profile.get("default_book_store_address", ""),
            book_name=book_title,
            author=book.get("author", ""),
            publisher=book.get("publisher", ""),
            description=book.get("description") or book_title,
            quantity=int(profile.get("default_book_quantity", 1)),
            price=str(varied_price),
            payment_method=profile.get("default_book_payment_method", "Online"),
            price_confirmed=True,
        ).model_dump(mode="json")
    if bill_type == "fuel":
        from_city = profile.get("default_from_city", "")
        to_city = profile.get("default_to_city", "")
        project_name = profile.get("project_name", "Client Project")
        from_pump_meta = DEFAULT_FUEL_PUMPS["from"]
        to_pump_meta = DEFAULT_FUEL_PUMPS["to"]
        from_receipt_city = profile_text(profile, "from_city_receipt_fuel_city", from_city)
        to_receipt_city = profile_text(profile, "to_city_receipt_fuel_city", to_city)
        from_pump = profile_text(profile, "from_city_pump_name", from_pump_meta["vendor"])
        to_pump = profile_text(profile, "to_city_pump_name", to_pump_meta["vendor"])
        from_pump_address = profile_text(profile, "from_city_pump_address", from_pump_meta["address"])
        to_pump_address = profile_text(profile, "to_city_pump_address", to_pump_meta["address"])
        from_pump_phone = profile_text(profile, "from_city_pump_phone", from_pump_meta["phone"])
        to_pump_phone = profile_text(profile, "to_city_pump_phone", to_pump_meta["phone"])
        rng = seeded_rng(
            "fuel",
            month,
            profile.get("employee_code", ""),
            profile.get("vehicle_number", ""),
            from_city,
            to_city,
        )
        used_receipts: set[str] = set()
        base_route_distance_km = route_distance_km(from_city, to_city)
        row_specs = []
        for week_index, (outbound_date, return_date) in enumerate(consecutive_working_day_pairs(month), start=1):
            outbound_km = route_leg_km(base_route_distance_km, week_index, rng)
            return_km = route_leg_km(base_route_distance_km, week_index, rng, return_leg=True)
            itinerary = trip_itinerary(outbound_date, return_date, outbound_km, return_km, rng)
            
            def random_base(val: str, spread: float) -> Decimal:
                return Decimal(val) + Decimal(str(round(rng.uniform(-spread, spread), 3)))

            outbound_litres = litres(random_base("31.90", 2.0) + Decimal(week_index) / Decimal("2"))
            to_litres = litres(random_base("20.75", 1.5) + Decimal(week_index))
            return_litres = litres(random_base("21.85", 1.5) + Decimal(week_index) / Decimal("1.5"))
            return_topup_litres = litres(random_base("10.80", 1.0) + Decimal(week_index) / Decimal("1.2"))
            # If the travel date is recent (within 14 days), fetch the exact real-world 
            # daily rate from Goodreturns. If it's an older month (or future), fallback 
            # to today's rate + a seeded monthly variance so it doesn't look identical.
            today = date.today()
            if not hasattr(rng, "city_prices"):
                rng.city_prices = {}
                
            def get_price(city: str, travel_date: date) -> tuple[str, str]:
                if 0 <= (today - travel_date).days <= 14:
                    return fuel_price_for(city, travel_date)
                
                if city not in rng.city_prices:
                    base_price_str, source = fuel_price_for(city, today)
                    city_rng = seeded_rng(month, profile.get("employee_name", ""), city)
                    variance = Decimal(str(round(city_rng.uniform(-0.60, 0.60), 2)))
                    rng.city_prices[city] = (Decimal(base_price_str) + variance, source)
                
                city_base, source = rng.city_prices[city]
                # Tiny daily variance so the same city isn't identical every single day
                daily_rng = seeded_rng(month, profile.get("employee_name", ""), city, travel_date.isoformat())
                daily_variance = Decimal(str(round(daily_rng.uniform(-0.15, 0.15), 2)))
                varied = (city_base + daily_variance).quantize(Decimal("0.01"))
                
                return str(varied), source

            from_price, from_source = get_price(from_receipt_city, outbound_date)
            to_price, to_source = get_price(to_receipt_city, outbound_date)
            return_price, return_source = get_price(to_receipt_city, return_date)
            return_topup_price, return_topup_source = get_price(from_receipt_city, return_date)
            row_specs.extend(
                [
                    (
                        outbound_date,
                        receipt_time(itinerary.outbound_departure),
                        from_city,
                        to_city,
                        str(outbound_km),
                        f"Client site visit regarding {project_name}",
                        from_receipt_city,
                        outbound_litres,
                        from_price,
                        from_pump,
                        from_pump_address,
                        from_pump_phone,
                        receipt_number(rng, used_receipts),
                        from_source,
                    ),
                    (
                        outbound_date,
                        receipt_time(itinerary.outbound_arrival + timedelta(minutes=rng.randrange(15, 36))),
                        from_city,
                        to_city,
                        "0",
                        f"Arrival top-up after reaching {to_city} for {project_name}",
                        to_receipt_city,
                        to_litres,
                        to_price,
                        to_pump,
                        to_pump_address,
                        to_pump_phone,
                        receipt_number(rng, used_receipts),
                        to_source,
                    ),
                    (
                        return_date,
                        receipt_time(itinerary.return_departure),
                        to_city,
                        from_city,
                        str(return_km),
                        f"Back to {from_city} Office from Client Site",
                        to_receipt_city,
                        return_litres,
                        return_price,
                        to_pump,
                        to_pump_address,
                        to_pump_phone,
                        receipt_number(rng, used_receipts),
                        return_source,
                    ),
                    (
                        return_date,
                        receipt_time(itinerary.return_arrival + timedelta(minutes=rng.randrange(10, 26))),
                        to_city,
                        from_city,
                        "0",
                        f"Arrival top-up after return to {from_city}",
                        from_receipt_city,
                        return_topup_litres,
                        return_topup_price,
                        from_pump,
                        from_pump_address,
                        from_pump_phone,
                        receipt_number(rng, used_receipts),
                        return_topup_source,
                    ),
                ]
            )
        rows = []
        for row in row_specs:
            rows.append(
                FuelLogRow(
                    date=row[0],
                    receipt_time=row[1],
                    from_city=row[2],
                    to_city=row[3],
                    km_travelled=row[4],
                    purpose=row[5],
                    fuel_city=row[6],
                    litres=row[7],
                    petrol_price_per_litre=row[8],
                    vendor=row[9],
                    vendor_logo_path=pump_logo_for(row[9]),
                    pump_address=row[10],
                    pump_phone=row[11],
                    receipt_number=row[12],
                    vehicle_number=profile["vehicle_number"],
                    customer_name=profile["employee_name"].split()[0],
                    price_source=row[13],
                )
            )
        return FuelBill(
            employee_name=profile["employee_name"],
            employee_code=profile["employee_code"],
            vehicle_number=profile["vehicle_number"],
            month=month,
            receipt_template=profile.get("default_fuel_receipt_template", "1"),
            rows=rows,
        ).model_dump(mode="json")
    raise ValueError(f"unknown bill type {bill_type}")
