"""Command-line interface for hletterscriptgen."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hletterscriptgen import LETTER_SET_SCHEMA_ID, __version__
from hletterscriptgen.upstream import UpstreamLoadError, explain_ineligible, load_entries
from hletterscriptgen.validation import validate_path

# Exit codes. ``EXIT_NOT_IMPLEMENTED`` follows the sysexits.h convention
# (``EX_UNAVAILABLE = 69``) to distinguish "feature not built yet" from
# argparse's usage error (exit code 2).
EXIT_OK = 0
EXIT_VALIDATION_FAILED = 1
EXIT_NOT_IMPLEMENTED = 69


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
        help="Validate a letter_set.v1 JSON document against schema and cross-field rules.",
    )
    validate_p.add_argument("path", type=Path, help="Path to a JSON letter-set document.")
    validate_p.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )

    sub.add_parser(
        "generate",
        help="(Not yet implemented) Generate letter sets from upstream scans.",
    )

    eligible_p = sub.add_parser(
        "check-eligible",
        help="Check which upstream entries pass the eligibility gate.",
    )
    eligible_p.add_argument(
        "entries_jsonl",
        type=Path,
        help="Path to an upstream entries.jsonl file.",
    )
    eligible_p.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )

    return parser


def _cmd_version() -> int:
    print(__version__)
    return EXIT_OK


def _cmd_schema(args: argparse.Namespace) -> int:
    if args.format == "json":
        json.dump({"schema_id": LETTER_SET_SCHEMA_ID}, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(LETTER_SET_SCHEMA_ID)
    return EXIT_OK


def _cmd_validate(args: argparse.Namespace) -> int:
    result = validate_path(args.path)
    if args.format == "json":
        payload = {
            "ok": result.ok,
            "path": str(args.path),
            "schema_id": LETTER_SET_SCHEMA_ID,
            "error_count": result.error_count,
            "errors": [
                {"path": i.path, "message": i.message, "kind": i.kind}
                for i in result.issues
            ],
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
    return EXIT_OK if result.ok else EXIT_VALIDATION_FAILED


def _cmd_check_eligible(args: argparse.Namespace) -> int:
    path: Path = args.entries_jsonl
    entry_ids: list[str] = []
    entry_reasons: list[list[str]] = []

    for entry in load_entries(path):
        entry_ids.append(entry.entry_id)
        entry_reasons.append(explain_ineligible(entry))

    total = len(entry_ids)
    ineligible_count = sum(1 for r in entry_reasons if r)
    eligible_count = total - ineligible_count
    ok = ineligible_count == 0

    if args.format == "json":
        payload: dict[str, object] = {
            "eligible": eligible_count,
            "entries": [
                {"eligible": not reasons, "entry_id": eid, "reasons": reasons}
                for eid, reasons in zip(entry_ids, entry_reasons, strict=True)
            ],
            "ineligible": ineligible_count,
            "ok": ok,
            "path": str(path),
            "total": total,
        }
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        for eid, reasons in zip(entry_ids, entry_reasons, strict=True):
            if not reasons:
                print(f"PASS {eid}")
            else:
                print(f"FAIL {eid}: {'; '.join(reasons)}")
        if ok:
            print(f"OK: {total}/{total} entries eligible")
        else:
            print(f"FAIL: {ineligible_count}/{total} entries ineligible")

    return EXIT_OK if ok else EXIT_VALIDATION_FAILED


def _cmd_generate() -> int:
    print(
        "generate: not yet implemented in this scaffolding release. "
        "See docs/roadmap.md for planned milestones.",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


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
    if args.command == "check-eligible":
        try:
            return _cmd_check_eligible(args)
        except UpstreamLoadError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    parser.error(f"unknown command: {args.command}")
