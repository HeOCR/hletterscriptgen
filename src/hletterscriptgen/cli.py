"""Command-line interface for hletterscriptgen."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hletterscriptgen import LETTER_SET_SCHEMA_ID, __version__
from hletterscriptgen.validation import validate_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hletterscriptgen",
        description=(
            "Generates per-writer Hebrew letter-glyph image sets from "
            "public-domain handwritten Hebrew scans."
        ),
    )
    parser.add_argument("--version", action="version", version=f"hletterscriptgen {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="Print the installed version.")

    schema_p = sub.add_parser("schema", help="Print the bundled letter_set schema id.")
    schema_p.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )

    validate_p = sub.add_parser(
        "validate",
        help="Validate a letter_set.v1 JSON document against the bundled schema.",
    )
    validate_p.add_argument("path", type=Path, help="Path to a JSON letter-set document.")
    validate_p.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )

    gen_p = sub.add_parser(
        "generate",
        help="(Not yet implemented) Generate letter sets from upstream scans.",
    )
    gen_p.add_argument("--input", type=Path, required=False)
    gen_p.add_argument("--output", type=Path, required=False)

    return parser


def _cmd_version() -> int:
    print(__version__)
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    if args.format == "json":
        json.dump({"schema_id": LETTER_SET_SCHEMA_ID}, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(LETTER_SET_SCHEMA_ID)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    result = validate_path(args.path)
    if args.format == "json":
        payload = {
            "ok": result.ok,
            "path": str(args.path),
            "schema_id": LETTER_SET_SCHEMA_ID,
            "error_count": result.error_count,
            "errors": [{"path": i.path, "message": i.message} for i in result.issues],
        }
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        if result.ok:
            print(f"OK {args.path} validates against {LETTER_SET_SCHEMA_ID}")
        else:
            print(f"FAIL {args.path} ({result.error_count} error(s))")
            for issue in result.issues:
                print(f"  - {issue.format()}")
    return 0 if result.ok else 1


def _cmd_generate() -> int:
    print(
        "generate: not yet implemented in this scaffolding release. "
        "See docs/roadmap.md for planned milestones.",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        return _cmd_version()
    if args.command == "schema":
        return _cmd_schema(args)
    if args.command == "validate":
        return _cmd_validate(args)
    if args.command == "generate":
        return _cmd_generate()

    parser.error(f"unknown command: {args.command}")
    return 2  # unreachable, parser.error exits
