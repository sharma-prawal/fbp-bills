from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

MONTH_FMT = "%Y-%m"


def parse_month(month: str) -> date:
    try:
        return datetime.strptime(month, MONTH_FMT).date().replace(day=1)
    except ValueError as exc:
        raise ValueError("month must be in YYYY-MM format") from exc


def month_label(month: str | date) -> str:
    value = parse_month(month) if isinstance(month, str) else month
    return value.strftime("%b %Y")


def month_name(month: str | date) -> str:
    value = parse_month(month) if isinstance(month, str) else month
    return value.strftime("%B")


def output_month_dir(month: str) -> str:
    return parse_month(month).strftime("%Y-%m")


def human_date(value: date | str) -> str:
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return value.strftime("%d-%m-%Y")


def short_human_date(value: date | str) -> str:
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return value.strftime("%-d-%b-%y")


def money(value: Decimal | float | int | str, places: int = 2) -> Decimal:
    quant = Decimal("1") if places == 0 else Decimal("0." + ("0" * (places - 1)) + "1")
    return Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)


def money_text(value: Decimal | float | int | str, places: int = 2) -> str:
    return f"{money(value, places):.{places}f}"


def filename_for(bill_type: str, month: str, ext: str = "pdf") -> str:
    label = month_label(month)
    mapping = {
        "internet": f"Internet Invoice {label}.{ext}",
        "driver": f"Driver Salary {label}.{ext}",
        "book": f"Book Invoice {label}.{ext}",
        "fuel": f"Fuel Bills {label}.{ext}",
        "fuel_logbook": f"Fuel Logbook {label}.{ext}",
    }
    if bill_type not in mapping:
        raise ValueError(f"unknown bill type: {bill_type}")
    return mapping[bill_type]

