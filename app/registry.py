from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class FieldMeta:
    label: str
    type: str
    required: bool = True
    editable_before_generation: bool = True
    editable_after_generation: bool = True
    default_source: str | None = None
    validation: str | None = None
    locked: bool = False
    calculated: bool = False


@dataclass(frozen=True)
class BillTypeConfig:
    key: str
    name: str
    model_name: str
    template: str
    output_filename_pattern: str
    fields: dict[str, FieldMeta]

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "model_name": self.model_name,
            "template": self.template,
            "output_filename_pattern": self.output_filename_pattern,
            "fields": {name: asdict(meta) for name, meta in self.fields.items()},
        }


BILL_TYPES: dict[str, BillTypeConfig] = {
    "internet": BillTypeConfig(
        key="internet",
        name="Internet Bill",
        model_name="InternetBill",
        template="bills/internet.html",
        output_filename_pattern="Internet Invoice {month_label}.pdf",
        fields={
            "provider_name": FieldMeta("Provider name", "text", default_source="profile.default_internet_provider"),
            "provider_address": FieldMeta("Provider address", "textarea"),
            "customer_name": FieldMeta("Customer name", "text", default_source="profile.employee_name"),
            "customer_address": FieldMeta("Customer address", "textarea", default_source="profile.address"),
            "account_number": FieldMeta("Account number", "text", default_source="profile.internet_account_number"),
            "invoice_number": FieldMeta("Invoice number", "text"),
            "bill_date": FieldMeta("Bill date", "date"),
            "amount": FieldMeta("Amount", "money", calculated=True),
            "plan_speed": FieldMeta("Plan speed", "text"),
            "plan_package": FieldMeta("Plan package", "text"),
            "tax.taxable_amount": FieldMeta("Taxable amount", "money"),
            "tax.cgst_rate": FieldMeta("CGST rate", "number"),
            "tax.sgst_rate": FieldMeta("SGST rate", "number"),
        },
    ),
    "driver": BillTypeConfig(
        key="driver",
        name="Driver Salary Receipt",
        model_name="DriverSalaryBill",
        template="bills/driver.html",
        output_filename_pattern="Driver Salary {month_label}.pdf",
        fields={
            "employee_name": FieldMeta("Employee name", "text", default_source="profile.employee_name"),
            "driver_name": FieldMeta("Driver name", "text", default_source="profile.default_driver_name"),
            "vehicle_number": FieldMeta("Vehicle number", "text", default_source="profile.vehicle_number"),
            "salary_amount": FieldMeta("Salary amount", "money", default_source="profile.default_driver_salary"),
            "month": FieldMeta("Month", "month", locked=True),
            "receipt_date": FieldMeta("Receipt date", "date"),
            "declaration_variant": FieldMeta("Declaration template", "select", locked=True),
            "revenue_stamp_asset_id": FieldMeta("Revenue stamp asset", "asset", required=False),
            "signature_asset_id": FieldMeta("Signature asset", "asset", required=False),
        },
    ),
    "book": BillTypeConfig(
        key="book",
        name="Book Receipt",
        model_name="BookBill",
        template="bills/book.html",
        output_filename_pattern="Book Invoice {month_label}.pdf",
        fields={
            "receipt_number": FieldMeta("Receipt number", "text"),
            "receipt_date": FieldMeta("Receipt date", "date"),
            "customer_name": FieldMeta("Customer name", "text", default_source="profile.employee_name"),
            "store_name": FieldMeta("Store name", "text"),
            "store_address": FieldMeta("Store address", "textarea"),
            "book_name": FieldMeta("Book name", "text"),
            "author": FieldMeta("Author", "text"),
            "publisher": FieldMeta("Publisher", "text"),
            "description": FieldMeta("Description", "textarea"),
            "quantity": FieldMeta("Quantity", "number"),
            "price": FieldMeta("Price", "money", validation="must be user-provided or confirmed"),
            "payment_method": FieldMeta("Payment method", "text"),
            "price_confirmed": FieldMeta("Price confirmed", "checkbox", locked=True),
        },
    ),
    "fuel": BillTypeConfig(
        key="fuel",
        name="Fuel Bills",
        model_name="FuelBill",
        template="bills/fuel_logbook.html",
        output_filename_pattern="Fuel Bills {month_label}.pdf",
        fields={
            "employee_name": FieldMeta("Employee name", "text", default_source="profile.employee_name"),
            "employee_code": FieldMeta("Employee code", "text", default_source="profile.employee_code"),
            "vehicle_number": FieldMeta("Vehicle number", "text", default_source="profile.vehicle_number"),
            "rows": FieldMeta("Monthly travel rows", "table", validation="every fuel price requires an explicit source"),
        },
    ),
}

