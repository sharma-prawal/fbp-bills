from __future__ import annotations

import json
from pathlib import Path

import fitz
from PIL import Image, ImageChops, ImageDraw

from app.config import BASE_DIR
from app.utils import filename_for, output_month_dir


REFERENCE_NAMES = {
    "internet": "Internet Invoice Jun 2026.pdf",
    "driver": "Driver Salary Jun 2026.pdf",
    "book": "Book Invoice Jun 2026.pdf",
    "fuel": "Fuel Bills Jun 2026.pdf",
}


def content_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    rgb = image.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, "white")).convert("L")
    mask = diff.point(lambda value: 255 if value > 12 else 0)
    return mask.getbbox()


def render_pdf_pages(pdf_path: Path, scale: float = 0.24) -> list[Image.Image]:
    doc = fitz.open(pdf_path)
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        images.append(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
    return images


def contact_sheet(items: list[tuple[str, Image.Image]], output_path: Path, columns: int = 4) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for label, image in items:
        frame = Image.new("RGB", (image.width + 16, image.height + 32), "white")
        draw = ImageDraw.Draw(frame)
        draw.text((8, 7), label, fill=(160, 0, 0))
        frame.paste(image, (8, 28))
        frames.append(frame)
    if not frames:
        raise ValueError("no pages available for visual audit")
    rows = (len(frames) + columns - 1) // columns
    col_width = max(frame.width for frame in frames) + 12
    row_height = max(frame.height for frame in frames) + 12
    sheet = Image.new("RGB", (columns * col_width, rows * row_height), "#eceff1")
    for idx, frame in enumerate(frames):
        sheet.paste(frame, ((idx % columns) * col_width + 6, (idx // columns) * row_height + 6))
    sheet.save(output_path)
    return output_path


def visual_audit(month: str) -> dict:
    out_dir = BASE_DIR / "output" / output_month_dir(month)
    audit_dir = out_dir / "visual_audit"
    generated = {
        "internet": out_dir / filename_for("internet", month, "pdf"),
        "driver": out_dir / filename_for("driver", month, "pdf"),
        "book": out_dir / filename_for("book", month, "pdf"),
        "fuel": out_dir / filename_for("fuel", month, "pdf"),
    }
    pages: list[tuple[str, Image.Image]] = []
    report: dict[str, dict] = {}
    for key, pdf_path in generated.items():
        if not pdf_path.exists():
            report[key] = {"status": "missing", "path": str(pdf_path)}
            continue
        images = render_pdf_pages(pdf_path)
        for index, image in enumerate(images, start=1):
            pages.append((f"{pdf_path.stem} p{index}", image))
        report[key] = {
            "status": "ok",
            "path": str(pdf_path),
            "pages": len(images),
            "content_boxes": [content_bbox(image) for image in images],
        }
        reference_path = BASE_DIR / "original-reference-docs" / REFERENCE_NAMES.get(key, "")
        if reference_path.exists():
            reference_images = render_pdf_pages(reference_path)
            report[key]["reference_pages"] = len(reference_images)
            report[key]["reference_content_boxes"] = [content_bbox(image) for image in reference_images]
    sheet_path = contact_sheet(pages, audit_dir / "generated_pages.png")
    report["contact_sheet"] = str(sheet_path)
    report_path = audit_dir / "visual_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
