from __future__ import annotations

import re
from html import unescape
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import httpx


CITY_SLUG_OVERRIDES = {
    "delhi": "new-delhi",
    "new delhi": "new-delhi",
}

# Largest gap (in days) between a requested date and the closest published rate
# for which an approximate fallback is still considered defensible.
MAX_APPROXIMATE_GAP_DAYS = 45


@dataclass(frozen=True)
class FuelPriceResult:
    city: str
    requested_date: date
    effective_date: date
    price_per_litre: Decimal
    source_url: str
    source_name: str = "goodreturns"
    approximate: bool = False
    note: str = ""


def city_slug(city: str) -> str:
    normalized = re.sub(r"\s+", " ", city.strip().lower())
    if normalized in CITY_SLUG_OVERRIDES:
        return CITY_SLUG_OVERRIDES[normalized]
    return normalized.replace(" ", "-")


def goodreturns_url(city: str) -> str:
    return f"https://www.goodreturns.in/petrol-price-in-{city_slug(city)}.html"


def effective_lookup_date(travel_date: date, today: date | None = None) -> date:
    return min(travel_date, today or date.today())


def parse_goodreturns_petrol_page(html: str, city: str, requested_date: date, source_url: str) -> FuelPriceResult:
    text = html_to_text(html)
    candidates = list(_daily_entries(text))

    today_match = re.search(r"Today's petrol price in .*? at ₹\s*([0-9]+(?:\.[0-9]+)?)\s*per litre", text, re.IGNORECASE | re.DOTALL)
    page_date_match = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+),\s+(\d{4})", text)
    if today_match and page_date_match:
        try:
            candidates.append((_parse_page_date(page_date_match.group(0)), Decimal(today_match.group(1))))
        except ValueError:
            pass

    if not candidates:
        raise ValueError(f"Could not parse petrol price for {city} on or before {requested_date.isoformat()}")

    eligible = [entry for entry in candidates if entry[0] <= requested_date]
    if eligible:
        effective_date, price = max(eligible, key=lambda item: item[0])
        return FuelPriceResult(city=city, requested_date=requested_date, effective_date=effective_date, price_per_litre=price, source_url=source_url)

    # Requested date is older than Goodreturns' rolling ~10-day history window.
    # Degrade gracefully: use the closest rate still published and flag it as
    # approximate so the stored price_source records that it is not exact. Only
    # do this within a sane window — a rate months away from the requested date
    # is not a defensible approximation, so require a manual price instead.
    effective_date, price = min(candidates, key=lambda item: item[0])
    gap_days = (effective_date - requested_date).days
    if gap_days > MAX_APPROXIMATE_GAP_DAYS:
        raise ValueError(
            f"No petrol price for {city} within {MAX_APPROXIMATE_GAP_DAYS} days of "
            f"{requested_date.isoformat()}; nearest published rate is {effective_date.isoformat()}"
        )
    return FuelPriceResult(
        city=city,
        requested_date=requested_date,
        effective_date=effective_date,
        price_per_litre=price,
        source_url=source_url,
        approximate=True,
        note=(
            f"exact rate for {requested_date.isoformat()} unavailable in Goodreturns' "
            f"rolling history; used closest published rate {effective_date.isoformat()} "
            f"({gap_days} day gap)"
        ),
    )


def fetch_goodreturns_petrol_price(city: str, requested_date: date, timeout: float = 12.0) -> FuelPriceResult:
    url = goodreturns_url(city)
    headers = {"User-Agent": "fbp-bills/0.1 local reimbursement tool"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
    return parse_goodreturns_petrol_page(response.text, city, requested_date, url)


def _daily_entries(html: str):
    pattern = re.compile(r"([A-Za-z]+ \d{1,2}, \d{4})\s*₹\s*([0-9]+(?:\.[0-9]+)?)")
    for match in pattern.finditer(html):
        yield datetime.strptime(match.group(1), "%B %d, %Y").date(), Decimal(match.group(2))


def _parse_page_date(text: str) -> date:
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", text)
    for fmt in ("%d %B, %Y", "%d %b, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"could not parse Goodreturns page date: {text}")


def html_to_text(html: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text)
