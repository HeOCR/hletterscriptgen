"""Validation helpers for letter_set.v1 documents.

Validation has two stages:

1. JSON Schema (Draft 2020-12) — structural shape and value constraints
   declared in :mod:`hletterscriptgen.schemas.letter_set.schema`.
2. Cross-field checks — invariants that span multiple parts of a
   document and cannot be expressed in JSON Schema alone:

   * ``license_summary.licenses`` (as a set) equals the set of distinct
     ``source.license`` values across all variants.
   * Every variant's ``source.scan_entry_id`` appears in
     ``writer_provenance.source_entry_ids``.
   * No variant's ``asset_path`` contains a ``..`` segment.

Cross-field checks run only when schema validation produced no errors;
they assume the document has the right shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import PurePosixPath
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


SCHEMA_PACKAGE = "hletterscriptgen.schemas"
SCHEMA_FILE = "letter_set.schema.json"

ISSUE_KIND_SCHEMA = "schema"
ISSUE_KIND_CROSS_FIELD = "cross_field"


def load_schema() -> dict[str, Any]:
    """Load the bundled letter_set.v1 JSON schema."""
    schema_text = (
        resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_FILE).read_text(encoding="utf-8")
    )
    return json.loads(schema_text)


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str
    kind: str  # ISSUE_KIND_SCHEMA or ISSUE_KIND_CROSS_FIELD

    def format(self) -> str:
        return f"[{self.kind}] {self.path or '<root>'}: {self.message}"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    issues: tuple[ValidationIssue, ...]

    @property
    def error_count(self) -> int:
        return len(self.issues)


def _schema_errors(document: Any) -> Iterable[ValidationIssue]:
    validator = Draft202012Validator(
        load_schema(),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    for error in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(part) for part in error.absolute_path)
        yield ValidationIssue(path=path, message=error.message, kind=ISSUE_KIND_SCHEMA)


def _iter_variants(document: dict[str, Any]) -> Iterable[tuple[str, int, dict[str, Any]]]:
    letters = document.get("letters", {})
    if not isinstance(letters, dict):
        return
    for letter, variants in letters.items():
        if not isinstance(variants, list):
            continue
        for index, variant in enumerate(variants):
            if isinstance(variant, dict):
                yield letter, index, variant


def _cross_field_errors(document: dict[str, Any]) -> Iterable[ValidationIssue]:
    summary_licenses = set(
        document.get("license_summary", {}).get("licenses", []) or []
    )
    observed_licenses: set[str] = set()
    declared_entries = set(
        document.get("writer_provenance", {}).get("source_entry_ids", []) or []
    )

    for letter, index, variant in _iter_variants(document):
        base_path = f"letters/{letter}/{index}"
        source = variant.get("source", {})

        license_value = source.get("license")
        if isinstance(license_value, str):
            observed_licenses.add(license_value)

        scan_entry_id = source.get("scan_entry_id")
        if isinstance(scan_entry_id, str) and scan_entry_id not in declared_entries:
            yield ValidationIssue(
                path=f"{base_path}/source/scan_entry_id",
                message=(
                    f"scan_entry_id '{scan_entry_id}' is not listed in "
                    "writer_provenance.source_entry_ids"
                ),
                kind=ISSUE_KIND_CROSS_FIELD,
            )

        asset_path = variant.get("asset_path")
        if isinstance(asset_path, str):
            segments = PurePosixPath(asset_path).parts
            if ".." in segments:
                yield ValidationIssue(
                    path=f"{base_path}/asset_path",
                    message=f"asset_path '{asset_path}' contains a '..' segment",
                    kind=ISSUE_KIND_CROSS_FIELD,
                )

    missing_from_summary = observed_licenses - summary_licenses
    extra_in_summary = summary_licenses - observed_licenses
    if missing_from_summary:
        yield ValidationIssue(
            path="license_summary/licenses",
            message=(
                "license_summary.licenses is missing licenses that appear in variants: "
                + ", ".join(sorted(missing_from_summary))
            ),
            kind=ISSUE_KIND_CROSS_FIELD,
        )
    if extra_in_summary:
        yield ValidationIssue(
            path="license_summary/licenses",
            message=(
                "license_summary.licenses contains licenses that no variant uses: "
                + ", ".join(sorted(extra_in_summary))
            ),
            kind=ISSUE_KIND_CROSS_FIELD,
        )


def validate_document(document: Any) -> ValidationResult:
    """Validate a parsed JSON document against schema and cross-field rules.

    Cross-field rules run only if schema validation produced no errors,
    since they assume the document has the right shape.
    """
    issues: list[ValidationIssue] = list(_schema_errors(document))
    if not issues and isinstance(document, dict):
        issues.extend(_cross_field_errors(document))
    return ValidationResult(ok=not issues, issues=tuple(issues))


def validate_path(path: Path) -> ValidationResult:
    """Validate a JSON document loaded from ``path``."""
    with path.open("r", encoding="utf-8") as fh:
        document = json.load(fh)
    return validate_document(document)
