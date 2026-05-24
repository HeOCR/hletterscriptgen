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
EXIT_INPUT_ERROR = 2  # mirrors argparse's convention for usage/input errors
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

    generate_p = sub.add_parser(
        "generate",
        help="Generate letter sets from upstream scans using a generation profile.",
    )
    generate_p.add_argument(
        "--profile",
        type=Path,
        required=True,
        metavar="PROFILE",
        help="Path to a generation profile JSON file.",
    )
    generate_p.add_argument(
        "--output",
        type=Path,
        required=True,
        metavar="DIR",
        help="Output directory (created if absent).",
    )
    generate_p.add_argument(
        "--generated-at",
        type=str,
        default=None,
        metavar="ISO8601",
        help=(
            "Override the generated_at timestamp in output documents "
            "(ISO 8601 format, e.g. '2025-01-01T00:00:00+00:00'). "
            "Useful for deterministic / reproducible builds."
        ),
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

    scan_blobs_p = sub.add_parser(
        "scan-blobs",
        help=(
            "Detect glyph blobs in a scan image via CCA. "
            "Use the output to populate a generation profile."
        ),
    )
    scan_blobs_p.add_argument(
        "image",
        type=Path,
        help="Path to the scan image (JPEG, PNG, TIFF, …).",
    )
    scan_blobs_p.add_argument(
        "--min-dim",
        type=int,
        default=16,
        metavar="PX",
        help="Minimum blob dimension in pixels (default: 16).",
    )
    scan_blobs_p.add_argument(
        "--max-area",
        type=int,
        default=None,
        metavar="PX2",
        help="Maximum blob area in pixels (default: 10%% of image area).",
    )
    scan_blobs_p.add_argument(
        "--format",
        choices=("text", "json"),
        default="json",
        help="Output format (default: json).",
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
    try:
        results = [
            (entry.entry_id, explain_ineligible(entry))
            for entry in load_entries(path)
        ]
    except UpstreamLoadError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INPUT_ERROR

    total = len(results)
    ineligible_count = sum(1 for _, reasons in results if reasons)
    eligible_count = total - ineligible_count
    ok = ineligible_count == 0

    if args.format == "json":
        payload = {
            "ok": ok,
            "path": str(path),
            "total": total,
            "eligible": eligible_count,
            "ineligible": ineligible_count,
            "entries": [
                {"entry_id": eid, "eligible": not reasons, "reasons": reasons}
                for eid, reasons in results
            ],
        }
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        for eid, reasons in results:
            if not reasons:
                print(f"PASS {eid}")
            else:
                print(f"FAIL {eid}: {'; '.join(reasons)}")
        if ok:
            print(f"OK: {total}/{total} entries eligible")
        else:
            print(f"FAIL: {ineligible_count}/{total} entries ineligible")

    return EXIT_OK if ok else EXIT_VALIDATION_FAILED


def _cmd_generate(args: argparse.Namespace) -> int:
    from hletterscriptgen.generate_profile import GenerateProfileError, load_generate_profile
    from hletterscriptgen.generator import GeneratorError, generate

    try:
        profile = load_generate_profile(args.profile)
    except GenerateProfileError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INPUT_ERROR

    try:
        output_paths = generate(
            profile,
            args.output,
            generated_at=args.generated_at,
        )
    except GeneratorError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INPUT_ERROR

    for p in output_paths:
        print(f"OK {p}")
    return EXIT_OK


def _cmd_scan_blobs(args: argparse.Namespace) -> int:
    from hletterscriptgen.extractor import ExtractionError, extract_glyphs

    try:
        glyphs = extract_glyphs(
            args.image,
            min_dimension=args.min_dim,
            max_area=args.max_area,
        )
    except ExtractionError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INPUT_ERROR

    if args.format == "json":
        payload = {
            "image": str(args.image),
            "count": len(glyphs),
            "blobs": [
                {"x": g.x, "y": g.y, "width": g.width, "height": g.height}
                for g in glyphs
            ],
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for i, g in enumerate(glyphs):
            print(f"blob {i:4d}: x={g.x:5d} y={g.y:5d} w={g.width:5d} h={g.height:5d}")
        print(f"{len(glyphs)} blob(s) detected in {args.image}")

    return EXIT_OK


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
        return _cmd_generate(args)
    if args.command == "check-eligible":
        return _cmd_check_eligible(args)
    if args.command == "scan-blobs":
        return _cmd_scan_blobs(args)

    parser.error(f"unknown command: {args.command}")
