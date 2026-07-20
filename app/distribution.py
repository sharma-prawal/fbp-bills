from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from app.config import BASE_DIR


EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "data",
    "dist",
    "original-reference-docs",
    "output",
    "tmp",
}

EXCLUDED_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".zip",
}

def build_sanitized_distribution(output_path: Path) -> Path:
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", ZIP_DEFLATED) as archive:
        for path in sorted(BASE_DIR.rglob("*")):
            relative = path.relative_to(BASE_DIR)
            if path == output_path or any(part in EXCLUDED_PARTS for part in relative.parts):
                continue
            if not path.is_file() or path.name == ".DS_Store" or path.suffix.lower() in EXCLUDED_SUFFIXES:
                continue
            if relative.parts[0] == "assets" and path.name.startswith("signature-"):
                continue
            archive.write(path, relative.as_posix())
        archive.writestr("assets/README.txt", "Add your own authorized logos, stamp, signature, texture, and receipt images here.\n")
        archive.writestr("data/.gitkeep", "")
        archive.writestr("output/.gitkeep", "")
    return output_path
