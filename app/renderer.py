from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pypdf import PdfWriter

_CACHE_DIR = Path(__file__).resolve().parent.parent / "tmp" / "cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_DIR))

from weasyprint import HTML

from app.config import BASE_DIR, TEMPLATES_DIR
from app.utils import human_date, money_text, month_label, month_name, short_human_date


def jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["human_date"] = human_date
    env.filters["short_human_date"] = short_human_date
    env.filters["money"] = money_text
    env.filters["output_url"] = output_url
    env.globals["month_label"] = month_label
    env.globals["month_name"] = month_name
    return env


def output_url(path: str | None) -> str:
    if not path:
        return ""
    value = Path(path)
    try:
        relative = value.relative_to(BASE_DIR)
    except ValueError:
        relative = value
    return "/" + relative.as_posix().lstrip("/")


def render_template(template: str, context: dict[str, Any]) -> str:
    return jinja_env().get_template(template).render(**context)


def html_to_pdf(html: str, output_path: Path, base_url: Path | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html, base_url=str(base_url or TEMPLATES_DIR)).write_pdf(output_path)
    return output_path


def merge_pdfs(paths: list[Path], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for path in paths:
        writer.append(str(path))
    with output_path.open("wb") as handle:
        writer.write(handle)
    return output_path
