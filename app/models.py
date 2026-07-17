from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Profile(BaseModel):
    employee_name: str
    employee_code: str
    address: str
    phone: str | None = None
    mobile_number: str | None = None
    email: str | None = None
    vehicle_number: str
    project_name: str | None = None
    default_from_city: str
    default_to_city: str
    from_city_receipt_fuel_city: str | None = None
    from_city_pump_name: str | None = None
    from_city_pump_address: str | None = None
    from_city_pump_phone: str | None = None
    to_city_receipt_fuel_city: str | None = None
    to_city_pump_name: str | None = None
    to_city_pump_address: str | None = None
    to_city_pump_phone: str | None = None
    default_internet_provider: str
    internet_account_number: str
    default_internet_bill_date: date | None = None
    default_driver_name: str
    default_driver_salary: Decimal = Field(gt=0)
    default_driver_receipt_date: date | None = None
    default_book_receipt_date: date | None = None
    default_book_price: Decimal | None = Field(default=None, gt=0)


class TaxFields(BaseModel):
    taxable_amount: Decimal = Field(ge=0)
    cgst_rate: Decimal = Field(default=Decimal("9"), ge=0)
    sgst_rate: Decimal = Field(default=Decimal("9"), ge=0)
    payments_received: Decimal | None = Field(default=None, ge=0)


class InternetBill(BaseModel):
    provider_name: str
    provider_address: str
    customer_name: str
    customer_address: str
    account_number: str
    invoice_number: str
    bill_date: date
    amount: Decimal = Field(gt=0)
    plan_speed: str
    plan_package: str
    plan_validity: str = "Monthly"
    discount: Decimal = Field(default=Decimal("0"), ge=0)
    payment_method: str = "Online"
    tax: TaxFields
    provider_logo_text: str | None = None
    provider_logo_path: str | None = None


class DriverSalaryBill(BaseModel):
    employee_name: str
    driver_name: str
    vehicle_number: str
    salary_amount: Decimal = Field(gt=0)
    month: str
    receipt_date: date
    declaration_variant: Literal["standard"] = "standard"
    template_style: Literal["1", "2"] = "1"
    revenue_stamp_asset_id: int | None = None
    signature_asset_id: int | None = None
    revenue_stamp_path: str | None = None
    signature_path: str | None = None
    stamp_x: float = 78
    stamp_y: float = 0
    stamp_scale: float = Field(default=1, gt=0)
    signature_x: float = -390
    signature_y: float = -88
    signature_scale: float = Field(default=1, gt=0)
    signature_rotation: float = -16


class BookBill(BaseModel):
    lookup_keyword: str | None = None
    receipt_number: str
    receipt_date: date
    customer_name: str
    store_name: str
    store_address: str
    book_name: str
    author: str
    publisher: str
    description: str
    quantity: int = Field(gt=0)
    price: Decimal = Field(gt=0)
    payment_method: str
    price_confirmed: bool = False

    @model_validator(mode="after")
    def require_price_confirmation(self) -> "BookBill":
        if not self.price_confirmed:
            raise ValueError("book price must be user-provided or explicitly confirmed")
        return self


class FuelLogRow(BaseModel):
    date: date
    receipt_time: time = time(8, 32)
    from_city: str
    to_city: str
    km_travelled: Decimal = Field(ge=0)
    purpose: str
    fuel_city: str
    litres: Decimal = Field(gt=0)
    petrol_price_per_litre: Decimal = Field(gt=0)
    vendor: str
    vendor_logo_path: str | None = None
    pump_address: str = ""
    pump_phone: str = ""
    receipt_number: str
    vehicle_number: str
    customer_name: str
    mode: str = "Online"
    price_source: str
    actual_receipt_image_path: str | None = None

    @field_validator("price_source")
    @classmethod
    def require_price_source(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("fuel price source is required")
        return value


class FuelBill(BaseModel):
    employee_name: str
    employee_code: str
    vehicle_number: str
    month: str
    receipt_template: Literal["1", "2", "3"] = "1"
    rows: list[FuelLogRow]

    @field_validator("rows")
    @classmethod
    def require_rows(cls, value: list[FuelLogRow]) -> list[FuelLogRow]:
        if not value:
            raise ValueError("at least one fuel row is required")
        return value


BillPayload = InternetBill | DriverSalaryBill | BookBill | FuelBill
