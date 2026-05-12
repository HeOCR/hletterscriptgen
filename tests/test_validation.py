"""Validation-level checks against the packaged example fixture."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from hletterscriptgen.validation import validate_document, validate_path


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "letter_set" / "writer_example.json"


@pytest.fixture(scope="module")
def example_document() -> dict:
    with EXAMPLE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_example_validates() -> None:
    result = validate_path(EXAMPLE)
    assert result.ok, [issue.format() for issue in result.issues]


def test_missing_required_field_fails(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    del doc["writer_id"]
    result = validate_document(doc)
    assert not result.ok
    assert any("writer_id" in issue.message for issue in result.issues)


def test_non_hebrew_letter_key_rejected(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    doc["letters"]["A"] = doc["letters"]["א"]
    result = validate_document(doc)
    assert not result.ok


def test_path_traversal_in_asset_rejected(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    doc["letters"]["א"][0]["asset_path"] = "../escape.png"
    result = validate_document(doc)
    assert not result.ok


def test_bad_checksum_format_rejected(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    doc["letters"]["א"][0]["checksum_sha256"] = "not-a-real-sha256"
    result = validate_document(doc)
    assert not result.ok


def test_unknown_format_rejected(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    doc["letters"]["א"][0]["image"]["format"] = "bmp"
    result = validate_document(doc)
    assert not result.ok
