import json
from app.services import merge_profile_precedence

profile = {
    "employee_name": "Test",
    "default_internet_provider": "Airtel",
    "default_internet_base_amount": "3999",
}

saved_payload = {
    "provider_name": "Airtel",
    "amount": "4718.82",
    "tax": {
        "taxable_amount": "4004.00",
        "cgst_rate": "9",
        "sgst_rate": "9",
        "payments_received": "4724.72"
    }
}

saved_audit = {
    "amount": {"source": "user_input_or_generated"},
    "tax": {
        "taxable_amount": {"source": "user_input_or_calculated"},
        "cgst_rate": {"source": "user_input_or_calculated"},
        "sgst_rate": {"source": "user_input_or_calculated"},
        "payments_received": {"source": "user_input_or_calculated"}
    }
}

result = merge_profile_precedence("internet", "2026-08", profile, saved_payload, saved_audit)
print("Merged Taxable Amount:", result["tax"]["taxable_amount"])
print("Merged Amount:", result["amount"])
