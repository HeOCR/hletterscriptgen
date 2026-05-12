"""Schema-level checks: the bundled schema is valid and self-consistent."""

from __future__ import annotations

from jsonschema import Draft202012Validator

from hletterscriptgen import ALLOWED_LICENSES, HEBREW_LETTERS
from hletterscriptgen.validation import load_schema


def test_schema_is_valid_draft_2020_12() -> None:
    schema = load_schema()
    Draft202012Validator.check_schema(schema)


def test_schema_declares_letter_set_v1_const() -> None:
    schema = load_schema()
    assert schema["properties"]["schema_version"]["const"] == "letter_set.v1"


def test_letters_pattern_accepts_hebrew_range() -> None:
    schema = load_schema()
    patterns = schema["properties"]["letters"]["patternProperties"]
    assert "^[א-ת]$" in patterns


def test_hebrew_letters_constant_has_27_codepoints() -> None:
    assert len(HEBREW_LETTERS) == 27
    assert "א" in HEBREW_LETTERS
    assert "ת" in HEBREW_LETTERS
    assert "ך" in HEBREW_LETTERS  # final-form kaf
    assert "ץ" in HEBREW_LETTERS  # final-form tsadi


def test_allowed_licenses_match_schema_enum() -> None:
    schema = load_schema()
    schema_enum = set(schema["$defs"]["license_id"]["enum"])
    assert set(ALLOWED_LICENSES) == schema_enum
