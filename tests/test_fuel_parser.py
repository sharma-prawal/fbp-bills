from datetime import date
from datetime import datetime
from decimal import Decimal

from app import db, services
from app.sample_data import route_distance_km, sample_payload
from app.services import parse_fuel_csv


class FakeRow(dict):
    def __getitem__(self, key):
        return self.get(key)


def test_parse_fuel_csv_can_lookup_blank_price(monkeypatch) -> None:
    def fake_fetch(city: str, row_date: date):
        return FakeRow(
            city=city,
            price_date=row_date.isoformat(),
            price_per_litre="102.12",
            source_type="goodreturns",
            source_url="https://example.test/source",
            note="fixture",
        )

    monkeypatch.setattr(services, "fetch_and_store_fuel_price", fake_fetch)
    profile = {
        "employee_name": "Sample Employee",
        "employee_code": "EMP-001",
        "vehicle_number": "TEST-1234",
    }
    csv_text = "\n".join(
        [
            "date,from_city,to_city,km_travelled,purpose,fuel_city,litres,petrol_price_per_litre,vendor,vendor_logo_path,pump_address,receipt_number,price_source,actual_receipt_image_path",
            '2026-06-15,Noida,Jodhpur,562,"Client visit",Delhi,10,,Bharat Petroleum,,Delhi outlet,1438,,',
        ]
    )
    payload = parse_fuel_csv(csv_text, profile, "2026-06")
    row = payload["rows"][0]
    assert row["petrol_price_per_litre"] == "102.12"
    assert "goodreturns" in row["price_source"]


def test_fuel_defaults_prefer_profile_pump_metadata(monkeypatch) -> None:
    def fake_price(city: str, row_date: date):
        return "101.00", f"test source {city} {row_date.isoformat()}"

    monkeypatch.setattr("app.sample_data.fuel_price_for", fake_price)
    profile = {
        "employee_name": "Sample Employee",
        "employee_code": "EMP-001",
        "vehicle_number": "TEST-1234",
        "project_name": "Sample Project",
        "default_from_city": "Noida",
        "default_to_city": "Jodhpur",
        "from_city_receipt_fuel_city": "Delhi",
        "from_city_pump_name": "Profile BP",
        "from_city_pump_address": "Profile BP Address",
        "from_city_pump_phone": "1111111",
        "to_city_receipt_fuel_city": "Jodhpur",
        "to_city_pump_name": "Profile IO",
        "to_city_pump_address": "Profile IO Address",
        "to_city_pump_phone": "2222222",
        "default_fuel_receipt_template": "2",
    }

    payload = sample_payload("fuel", "2026-06", profile)
    first = payload["rows"][0]
    second = payload["rows"][1]

    assert first["vendor"] == "Profile BP"
    assert first["pump_address"] == "Profile BP Address"
    assert first["pump_phone"] == "1111111"
    assert second["vendor"] == "Profile IO"
    assert second["pump_address"] == "Profile IO Address"
    assert second["pump_phone"] == "2222222"


def test_future_month_generates_future_travel_dates(monkeypatch) -> None:
    def fake_price(city: str, row_date: date):
        return "101.00", f"latest current price for future row {row_date.isoformat()}"

    monkeypatch.setattr("app.sample_data.fuel_price_for", fake_price)
    profile = {
        "employee_name": "Sample Employee",
        "employee_code": "EMP-001",
        "vehicle_number": "TEST-1234",
        "project_name": "Sample Project",
        "default_from_city": "Noida",
        "default_to_city": "Jodhpur",
    }

    payload = sample_payload("fuel", "2027-02", profile)

    assert payload["month"] == "2027-02"
    assert all(row["date"].startswith("2027-02-") for row in payload["rows"])


def complete_fuel_profile() -> dict:
    return {
        "employee_name": "Sample Employee",
        "employee_code": "EMP-001",
        "vehicle_number": "TEST-1234",
        "project_name": "Sample Project",
        "default_from_city": "Noida",
        "default_to_city": "Jodhpur",
        "from_city_receipt_fuel_city": "Delhi",
        "from_city_pump_name": "Profile BP",
        "from_city_pump_address": "Profile BP Address",
        "from_city_pump_phone": "1111111",
        "to_city_receipt_fuel_city": "Jodhpur",
        "to_city_pump_name": "Profile IO",
        "to_city_pump_address": "Profile IO Address",
        "to_city_pump_phone": "2222222",
        "default_fuel_receipt_template": "2",
    }


def row_datetime(row: dict) -> datetime:
    return datetime.fromisoformat(f"{row['date']}T{row['receipt_time']}")


def test_route_distance_uses_configured_cities() -> None:
    assert route_distance_km("Noida", "Jodhpur") == 561
    assert route_distance_km("Unknown City", "Jodhpur") == 560


def test_fuel_receipt_numbers_are_seeded_and_varied(monkeypatch) -> None:
    def fake_price(city: str, row_date: date):
        return "101.00", f"test source {city} {row_date.isoformat()}"

    monkeypatch.setattr("app.sample_data.fuel_price_for", fake_price)
    profile = complete_fuel_profile()

    first = sample_payload("fuel", "2026-06", profile)
    second = sample_payload("fuel", "2026-06", profile)
    next_month = sample_payload("fuel", "2026-07", profile)

    first_numbers = [row["receipt_number"] for row in first["rows"]]
    assert first_numbers == [row["receipt_number"] for row in second["rows"]]
    assert first_numbers != [row["receipt_number"] for row in next_month["rows"]]
    assert len(first_numbers) == len(set(first_numbers))


def test_fuel_rows_are_four_receipt_round_trip_sets(monkeypatch) -> None:
    def fake_price(city: str, row_date: date):
        return "101.00", f"test source {city} {row_date.isoformat()}"

    monkeypatch.setattr("app.sample_data.fuel_price_for", fake_price)
    payload = sample_payload("fuel", "2026-06", complete_fuel_profile())
    rows = payload["rows"]

    assert len(rows) % 4 == 0
    for index in range(0, len(rows), 4):
        outbound, arrival_topup, return_leg, return_topup = rows[index : index + 4]
        outbound_departure = row_datetime(outbound)
        outbound_arrival_topup = row_datetime(arrival_topup)
        return_departure = row_datetime(return_leg)
        return_arrival_topup = row_datetime(return_topup)

        assert outbound["from_city"] == "Noida"
        assert outbound["to_city"] == "Jodhpur"
        assert outbound["purpose"] == "Client site visit regarding Sample Project"
        assert arrival_topup["km_travelled"] == "0"
        assert return_leg["from_city"] == "Jodhpur"
        assert return_leg["to_city"] == "Noida"
        assert return_leg["purpose"] == "Back to Noida Office from Client Site"
        assert return_topup["km_travelled"] == "0"
        assert outbound_departure.hour == 8
        assert return_departure.hour == 8
        assert Decimal(outbound["km_travelled"]) >= Decimal("546")
        assert Decimal(return_leg["km_travelled"]) >= Decimal("520")
        assert 8 <= (outbound_arrival_topup - outbound_departure).total_seconds() / 3600 <= 9.75
        assert 8 <= (return_arrival_topup - return_departure).total_seconds() / 3600 <= 9.5
        assert "around" not in outbound["purpose"]
        assert ":" not in outbound["purpose"]
        assert "Arrival top-up" in arrival_topup["purpose"]
        assert "Arrival top-up" in return_topup["purpose"]
