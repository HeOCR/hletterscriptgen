"""Validation helpers for letter_set.v1 documents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


SCHEMA_PACKAGE = "hletterscriptgen.schemas"
SCHEMA_FILE = "letter_set.schema.json"


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

    def format(self) -> str:
        return f"{self.path or '<root>'}: {self.message}"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    issues: tuple[ValidationIssue, ...]

    @property
    def error_count(self) -> int:
        return len(self.issues)


def validate_document(document: Any) -> ValidationResult:
    """Validate a parsed JSON document against the letter_set.v1 schema."""
    validator = Draft202012Validator(load_schema())
    issues: list[ValidationIssue] = []
    for error in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(part) for part in error.absolute_path)
        issues.append(ValidationIssue(path=path, message=error.message))
    return ValidationResult(ok=not issues, issues=tuple(issues))


def validate_path(path: Path) -> ValidationResult:
    """Validate a JSON document loaded from `path`."""
    with path.open("r", encoding="utf-8") as fh:
        document = json.load(fh)
    return validate_document(document)
