"""Validation-level checks against the packaged example fixture."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from hletterscriptgen.validation import (
    ISSUE_KIND_CROSS_FIELD,
    ISSUE_KIND_SCHEMA,
    validate_document,
    validate_path,
)


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "letter_set" / "writer_example.json"


@pytest.fixture(scope="module")
def example_document() -> dict:
    with EXAMPLE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# --- positive ----------------------------------------------------------------


def test_example_validates() -> None:
    result = validate_path(EXAMPLE)
    assert result.ok, [issue.format() for issue in result.issues]


# --- schema-level negatives --------------------------------------------------


def test_missing_required_field_fails(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    del doc["writer_id"]
    result = validate_document(doc)
    assert not result.ok
    assert any("writer_id" in issue.message for issue in result.issues)


def test_missing_writer_provenance_fails(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    del doc["writer_provenance"]
    result = validate_document(doc)
    assert not result.ok
    assert all(issue.kind == ISSUE_KIND_SCHEMA for issue in result.issues)


def test_missing_upstream_fails(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    del doc["upstream"]
    result = validate_document(doc)
    assert not result.ok


def test_missing_bbox_in_source_fails(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    del doc["letters"]["א"][0]["source"]["bbox_in_source"]
    result = validate_document(doc)
    assert not result.ok


def test_non_hebrew_letter_key_rejected(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    doc["letters"]["A"] = doc["letters"]["א"]
    result = validate_document(doc)
    assert not result.ok


def test_leading_slash_in_asset_rejected(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    doc["letters"]["א"][0]["asset_path"] = "/letters/alef/x.png"
    result = validate_document(doc)
    assert not result.ok
    assert any(issue.kind == ISSUE_KIND_SCHEMA for issue in result.issues)


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


def test_disallowed_license_rejected(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    doc["letters"]["א"][0]["source"]["license"] = "GPL-3.0"
    result = validate_document(doc)
    assert not result.ok


def test_short_config_hash_rejected(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    doc["generator"]["config_hash"] = "abc123"
    result = validate_document(doc)
    assert not result.ok


def test_malformed_date_time_rejected(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    doc["generated_at"] = "not-a-date"
    result = validate_document(doc)
    assert not result.ok


def test_malformed_scan_url_rejected(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    doc["letters"]["א"][0]["source"]["scan_url"] = "not a uri"
    result = validate_document(doc)
    assert not result.ok


# --- cross-field negatives ---------------------------------------------------


def test_path_traversal_in_asset_rejected(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    doc["letters"]["א"][0]["asset_path"] = "letters/../escape.png"
    result = validate_document(doc)
    assert not result.ok
    assert any(issue.kind == ISSUE_KIND_CROSS_FIELD for issue in result.issues)


def test_license_summary_missing_license_rejected(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    doc["license_summary"]["licenses"] = ["PDM-1.0"]  # drop CC-BY-SA-4.0 deliberately
    result = validate_document(doc)
    assert not result.ok
    assert any(
        issue.kind == ISSUE_KIND_CROSS_FIELD and "missing" in issue.message
        for issue in result.issues
    )


def test_license_summary_extra_license_rejected(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    doc["license_summary"]["licenses"] = ["PDM-1.0", "CC-BY-SA-4.0", "CC-BY-4.0"]
    result = validate_document(doc)
    assert not result.ok
    assert any(
        issue.kind == ISSUE_KIND_CROSS_FIELD and "no variant uses" in issue.message
        for issue in result.issues
    )


def test_scan_entry_id_not_in_provenance_rejected(example_document: dict) -> None:
    doc = copy.deepcopy(example_document)
    doc["letters"]["א"][0]["source"]["scan_entry_id"] = "example-scan-9999"
    result = validate_document(doc)
    assert not result.ok
    assert any(
        issue.kind == ISSUE_KIND_CROSS_FIELD
        and "not listed in writer_provenance.source_entry_ids" in issue.message
        for issue in result.issues
    )
