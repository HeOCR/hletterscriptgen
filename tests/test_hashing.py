"""Tests for canonical-JSON config hashing."""

from __future__ import annotations

import re

from hletterscriptgen import ALLOWED_LICENSES, canonical_json, config_hash
from hletterscriptgen.validation import load_schema

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def test_config_hash_matches_schema_pattern() -> None:
    schema = load_schema()
    pattern = schema["properties"]["generator"]["properties"]["config_hash"]["pattern"]
    digest = config_hash({"any": "value"})
    assert HEX64.fullmatch(digest)
    assert re.fullmatch(pattern, digest)


def test_config_hash_is_deterministic() -> None:
    payload = {"sources": ["nli", "biblia"], "writers": 17}
    assert config_hash(payload) == config_hash(payload)


def test_config_hash_is_key_order_independent() -> None:
    a = {"a": 1, "b": 2, "nested": {"x": 1, "y": 2}}
    b = {"b": 2, "a": 1, "nested": {"y": 2, "x": 1}}
    assert config_hash(a) == config_hash(b)


def test_config_hash_distinguishes_different_configs() -> None:
    assert config_hash({"writers": 17}) != config_hash({"writers": 18})


def test_canonical_json_has_no_whitespace_and_sorted_keys() -> None:
    blob = canonical_json({"b": 1, "a": [3, 2, 1]})
    assert blob == b'{"a":[3,2,1],"b":1}'


def test_canonical_json_preserves_unicode() -> None:
    blob = canonical_json({"letter": "א"})
    assert "א".encode() in blob


def test_config_hash_output_is_a_valid_license_unrelated_check() -> None:
    # Sanity: the hash output is a string distinct from any license id.
    digest = config_hash({"x": 1})
    assert digest not in ALLOWED_LICENSES
