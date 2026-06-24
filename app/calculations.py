from __future__ import annotations

from decimal import Decimal

from app.models import BookBill, FuelBill, InternetBill
from app.utils import money


def internet_totals(data: InternetBill) -> dict[str, Decimal]:
    cgst = money(data.tax.taxable_amount * data.tax.cgst_rate / Decimal("100"))
    sgst = money(data.tax.taxable_amount * data.tax.sgst_rate / Decimal("100"))
    total = money(data.tax.taxable_amount + cgst + sgst - data.discount)
    received = data.tax.payments_received if data.tax.payments_received is not None else total
    return {"cgst_amount": cgst, "sgst_amount": sgst, "total_amount": total, "payments_received": money(received)}


def book_totals(data: BookBill) -> dict[str, Decimal]:
    return {"line_total": money(data.price * data.quantity), "total_amount": money(data.price * data.quantity)}


def fuel_row_amount(litres: Decimal, price: Decimal) -> Decimal:
    return money(litres * price, 0)


def fuel_totals(data: FuelBill) -> dict[str, Decimal]:
    total_litres = sum((row.litres for row in data.rows), Decimal("0"))
    total_amount = sum((fuel_row_amount(row.litres, row.petrol_price_per_litre) for row in data.rows), Decimal("0"))
    total_km = sum((row.km_travelled for row in data.rows), Decimal("0"))
    return {
        "total_litres": money(total_litres),
        "total_amount": money(total_amount, 0),
        "total_km": money(total_km, 0),
    }

