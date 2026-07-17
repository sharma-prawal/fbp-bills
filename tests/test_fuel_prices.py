from datetime import date

import pytest

from app.fuel_prices import city_slug, parse_goodreturns_petrol_page


def test_city_slug_special_cases() -> None:
    assert city_slug("Delhi") == "new-delhi"
    assert city_slug("New Delhi") == "new-delhi"
    assert city_slug("Jodhpur") == "jodhpur"


def test_parse_goodreturns_daily_price_on_or_before_date() -> None:
    html = """
    Today's petrol price in Noida is at ₹102.09 per litre.
    Last 10 Days Petrol Rate in Noida
    Date Price Price Change
    June 18, 2026 ₹102.12 +0.16
    June 17, 2026 ₹101.96 -0.16
    June 11, 2026 ₹102.12 0.00
    """
    result = parse_goodreturns_petrol_page(html, "Noida", date(2026, 6, 15), "https://example.test/noida")
    assert result.effective_date == date(2026, 6, 11)
    assert str(result.price_per_litre) == "102.12"
    assert result.approximate is False


def test_parse_goodreturns_falls_back_when_date_predates_rolling_window() -> None:
    # Requested July 1, but the source's rolling history only reaches back to July 6.
    html = """
    Today's petrol price in Noida is at ₹102.09 per litre. 17th Jul, 2026
    Last 10 Days Petrol Rate in Noida
    Date Price Price Change
    July 15, 2026 ₹102.12 0.00
    July 10, 2026 ₹101.96 -0.16
    July 6, 2026 ₹101.80 0.00
    """
    result = parse_goodreturns_petrol_page(html, "Noida", date(2026, 7, 1), "https://example.test/noida")
    assert result.approximate is True
    assert result.effective_date == date(2026, 7, 6)
    assert str(result.price_per_litre) == "101.80"
    assert "unavailable" in result.note


def test_parse_goodreturns_raises_when_no_data_at_all() -> None:
    with pytest.raises(ValueError):
        parse_goodreturns_petrol_page("no prices here", "Noida", date(2026, 7, 1), "https://example.test/noida")


def test_parse_goodreturns_raises_when_nearest_rate_is_too_far() -> None:
    # Requested date is months before anything the page still publishes; an
    # approximation that far off is not defensible, so it must raise.
    html = """
    Today's petrol price in Noida is at ₹102.09 per litre. 17th Jul, 2026
    Last 10 Days Petrol Rate in Noida
    Date Price Price Change
    July 15, 2026 ₹102.12 0.00
    July 6, 2026 ₹101.80 0.00
    """
    with pytest.raises(ValueError):
        parse_goodreturns_petrol_page(html, "Noida", date(2026, 3, 1), "https://example.test/noida")
