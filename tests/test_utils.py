from datetime import date

import pytest

from app.fuel_prices import effective_lookup_date
from app.sample_data import profile_date_for_month
from app.utils import filename_for, human_date, month_label, month_name, parse_month


def test_month_formatting() -> None:
    assert parse_month("2026-06") == date(2026, 6, 1)
    assert month_label("2026-06") == "Jun 2026"
    assert month_name("2026-06") == "June"


def test_date_formatting() -> None:
    assert human_date(date(2026, 6, 14)) == "14-06-2026"


def test_filename_generation() -> None:
    assert filename_for("internet", "2026-06") == "Internet Invoice Jun 2026.pdf"
    assert filename_for("fuel_logbook", "2026-06", "xlsx") == "Fuel Logbook Jun 2026.xlsx"
    with pytest.raises(ValueError):
        filename_for("unknown", "2026-06")


def test_profile_calendar_day_moves_to_selected_month() -> None:
    profile = {"default_book_receipt_date": "2026-06-14"}
    assert profile_date_for_month(profile, "default_book_receipt_date", "2027-02", 14) == date(2027, 2, 14)


def test_profile_calendar_day_is_clamped_for_short_month() -> None:
    profile = {"default_book_receipt_date": "2026-01-31"}
    assert profile_date_for_month(profile, "default_book_receipt_date", "2027-02", 14) == date(2027, 2, 28)


def test_future_fuel_lookup_uses_today() -> None:
    today = date(2026, 6, 24)
    assert effective_lookup_date(date(2027, 1, 10), today) == today
    assert effective_lookup_date(date(2026, 5, 10), today) == date(2026, 5, 10)
