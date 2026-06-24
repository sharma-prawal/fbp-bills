from __future__ import annotations

import re
from pathlib import Path

from app.config import ASSETS_DIR

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def find_asset(*keywords: str) -> str | None:
    wanted = [normalize(keyword) for keyword in keywords if keyword]
    if not wanted:
        return None
    for path in sorted(ASSETS_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        name = normalize(path.stem)
        if all(keyword in name for keyword in wanted):
            return str(path.relative_to(ASSETS_DIR.parent))
    return None


def internet_logo_for(provider: str) -> str | None:
    provider_key = normalize(provider)
    for keyword in ("airtel", "jio", "hathway", "vodafone", "act"):
        if keyword in provider_key:
            return find_asset("logo", keyword)
    return find_asset("logo", "general")


def pump_logo_for(vendor: str) -> str | None:
    vendor_key = normalize(vendor)
    mappings = [
        (("bharat", "bpcl"), ("pump", "bharat")),
        (("indian", "iocl"), ("pump", "indian")),
        (("hindustan", "hpcl", "hp"), ("pump", "hp")),
        (("essar",), ("pump", "essar")),
    ]
    for aliases, search_terms in mappings:
        if any(alias in vendor_key for alias in aliases):
            return find_asset(*search_terms)
    return None


def revenue_stamp_path() -> str | None:
    return find_asset("revenu") or find_asset("revenue")


def signature_for(name: str) -> str | None:
    parts = normalize(name).split("-")
    for part in parts:
        if part:
            found = find_asset("signature", part)
            if found:
                return found
    return None


def receipt_texture_path() -> str | None:
    return find_asset("texture")


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
