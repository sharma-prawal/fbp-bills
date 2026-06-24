from __future__ import annotations

import argparse
import json
from pathlib import Path

from app import db
from app.config import DB_PATH
from app.distribution import build_sanitized_distribution
from app.services import default_user_id, ensure_seeded, export_bundle, generate_bill, preview_html
from app.visual_audit import visual_audit


def cmd_init_db(args: argparse.Namespace) -> None:
    db.initialize_installation(DB_PATH)
    print(f"Initialized database at {DB_PATH}")


def cmd_generate(args: argparse.Namespace) -> None:
    user_id = ensure_seeded()
    payload = json.loads(Path(args.input_json).read_text(encoding="utf-8")) if args.input_json else None
    result = generate_bill(user_id, args.type, args.month, payload)
    print(json.dumps(result, indent=2))


def cmd_preview(args: argparse.Namespace) -> None:
    user_id = ensure_seeded()
    html, _ = preview_html(user_id, args.type, args.month)
    output = Path(args.output or f"output/preview-{args.type}-{args.month}.html")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    print(output)


def cmd_export_bundle(args: argparse.Namespace) -> None:
    ensure_seeded()
    path = export_bundle(args.month)
    print(path)


def cmd_visual_audit(args: argparse.Namespace) -> None:
    ensure_seeded()
    result = visual_audit(args.month)
    print(json.dumps(result, indent=2))


def cmd_prepare_share(args: argparse.Namespace) -> None:
    output = Path(args.output or "dist/fbp-bills-share.zip")
    path = build_sanitized_distribution(output)
    print(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.main")
    sub = parser.add_subparsers(required=True)

    init = sub.add_parser("init-db")
    init.set_defaults(func=cmd_init_db)

    generate = sub.add_parser("generate")
    generate.add_argument("--month", required=True)
    generate.add_argument("--type", required=True, choices=["internet", "driver", "book", "fuel", "all"])
    generate.add_argument("--input-json")
    generate.set_defaults(func=cmd_generate)

    preview = sub.add_parser("preview")
    preview.add_argument("--month", required=True)
    preview.add_argument("--type", required=True, choices=["internet", "driver", "book", "fuel"])
    preview.add_argument("--output")
    preview.set_defaults(func=cmd_preview)

    bundle = sub.add_parser("export-bundle")
    bundle.add_argument("--month", required=True)
    bundle.set_defaults(func=cmd_export_bundle)

    audit = sub.add_parser("visual-audit")
    audit.add_argument("--month", required=True)
    audit.set_defaults(func=cmd_visual_audit)

    share = sub.add_parser("prepare-share")
    share.add_argument("--output")
    share.set_defaults(func=cmd_prepare_share)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
