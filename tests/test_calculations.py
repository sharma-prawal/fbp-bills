from datetime import date

from app.calculations import book_totals, fuel_totals, internet_totals
from app.models import BookBill, FuelBill, FuelLogRow, InternetBill, TaxFields


def test_tax_calculations() -> None:
    bill = InternetBill(
        provider_name="Airtel",
        provider_address="Faridabad",
        customer_name="Sample Employee",
        customer_address="Faridabad",
        account_number="9000000000",
        invoice_number="IN1853",
        bill_date=date(2026, 6, 3),
        amount="4718.82",
        plan_speed="1Gbps",
        plan_package="Unlimited",
        tax=TaxFields(taxable_amount="3999.00", cgst_rate="9", sgst_rate="9", payments_received="4718.82"),
    )
    totals = internet_totals(bill)
    assert totals["cgst_amount"].to_eng_string() == "359.91"
    assert totals["sgst_amount"].to_eng_string() == "359.91"
    assert totals["total_amount"].to_eng_string() == "4718.82"


def test_fuel_totals() -> None:
    row = FuelLogRow(
        date=date(2026, 6, 1),
        from_city="Noida",
        to_city="Jodhpur",
        km_travelled="567",
        purpose="Client visit",
        fuel_city="Delhi",
        litres="32.45",
        petrol_price_per_litre="102.12",
        vendor="Bharat Petroleum",
        receipt_number="1430",
        vehicle_number="TEST-1234",
        customer_name="Sample",
        price_source="manual record",
    )
    totals = fuel_totals(FuelBill(employee_name="Sample Employee", employee_code="EMP-001", vehicle_number="TEST-1234", month="2026-06", rows=[row]))
    assert totals["total_km"].to_eng_string() == "567"
    assert totals["total_litres"].to_eng_string() == "32.45"
    assert totals["total_amount"].to_eng_string() == "3314"


def test_book_totals() -> None:
    bill = BookBill(
        receipt_number="R1",
        receipt_date=date(2026, 6, 14),
        customer_name="Sample Employee",
        store_name="Sample Books",
        store_address="Delhi",
        book_name="Open Magazine",
        author="Open Media",
        publisher="Open Media",
        description="Magazine",
        quantity=2,
        price="100.50",
        payment_method="Online",
        price_confirmed=True,
    )
    assert book_totals(bill)["total_amount"].to_eng_string() == "201.00"
