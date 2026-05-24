"""Tests for the generation profile loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hletterscriptgen.generate_profile import (
    GenerateProfile,
    GenerateProfileError,
    GlyphAnnotation,
    ScanAnnotation,
    WriterAnnotation,
    load_generate_profile,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "generate_profile"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_profile(tmp_path: Path, payload: object) -> Path:
    p = tmp_path / "profile.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


_MINIMAL_GLYPH = {"letter": "א", "x": 0, "y": 0, "width": 20, "height": 20}
_MINIMAL_SCAN = {"entry_id": "e__s__p0001", "glyphs": [_MINIMAL_GLYPH]}
_MINIMAL_WRITER = {
    "writer_id": "w1",
    "attribution_method": "manual_review",
    "scans": [_MINIMAL_SCAN],
}
_MINIMAL_PROFILE = {
    "upstream_checkout": ".",
    "writers": [_MINIMAL_WRITER],
}


# ---------------------------------------------------------------------------
# Valid profile
# ---------------------------------------------------------------------------


def test_load_valid_fixture() -> None:
    profile, raw = load_generate_profile(FIXTURE_DIR / "valid_profile.json")
    assert isinstance(profile, GenerateProfile)
    assert len(profile.writers) == 1
    writer = profile.writers[0]
    assert writer.writer_id == "writer_fixture_a"
    assert writer.attribution_method == "manual_review"
    assert writer.notes == "Fixture writer for tests"
    assert len(writer.scans) == 1
    scan = writer.scans[0]
    assert scan.entry_id == "fixture__eligible_pdm__p0001"
    assert len(scan.glyphs) == 2
    assert scan.glyphs[0].letter == "א"
    assert scan.glyphs[1].letter == "ב"
    assert isinstance(raw, dict)


def test_load_returns_raw_dict(tmp_path: Path) -> None:
    p = _write_profile(tmp_path, _MINIMAL_PROFILE)
    _, raw = load_generate_profile(p)
    assert raw == _MINIMAL_PROFILE


def test_upstream_checkout_resolved_relative_to_profile(tmp_path: Path) -> None:
    sub = tmp_path / "configs"
    sub.mkdir()
    p = sub / "profile.json"
    p.write_text(json.dumps({**_MINIMAL_PROFILE, "upstream_checkout": "../data"}), encoding="utf-8")
    profile, _ = load_generate_profile(p)
    assert profile.upstream_checkout == (tmp_path / "data").resolve()


def test_glyph_notes_optional(tmp_path: Path) -> None:
    glyph_with_notes = {**_MINIMAL_GLYPH, "notes": "a test note"}
    profile_data = {
        "upstream_checkout": ".",
        "writers": [
            {**_MINIMAL_WRITER, "scans": [{"entry_id": "e__s__p0001", "glyphs": [glyph_with_notes]}]},
        ],
    }
    p = _write_profile(tmp_path, profile_data)
    profile, _ = load_generate_profile(p)
    assert profile.writers[0].scans[0].glyphs[0].notes == "a test note"


# ---------------------------------------------------------------------------
# File-level errors
# ---------------------------------------------------------------------------


def test_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(GenerateProfileError, match="not found"):
        load_generate_profile(tmp_path / "nonexistent.json")


def test_raises_on_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "profile.json"
    p.write_text("{not valid", encoding="utf-8")
    with pytest.raises(GenerateProfileError, match="invalid JSON"):
        load_generate_profile(p)


def test_raises_on_non_object_root(tmp_path: Path) -> None:
    p = _write_profile(tmp_path, [1, 2, 3])
    with pytest.raises(GenerateProfileError, match="JSON object"):
        load_generate_profile(p)


# ---------------------------------------------------------------------------
# upstream_checkout validation
# ---------------------------------------------------------------------------


def test_raises_on_missing_upstream_checkout(tmp_path: Path) -> None:
    payload = {k: v for k, v in _MINIMAL_PROFILE.items() if k != "upstream_checkout"}
    p = _write_profile(tmp_path, payload)
    with pytest.raises(GenerateProfileError, match="upstream_checkout"):
        load_generate_profile(p)


def test_raises_on_blank_upstream_checkout(tmp_path: Path) -> None:
    p = _write_profile(tmp_path, {**_MINIMAL_PROFILE, "upstream_checkout": "   "})
    with pytest.raises(GenerateProfileError, match="upstream_checkout"):
        load_generate_profile(p)


# ---------------------------------------------------------------------------
# writers validation
# ---------------------------------------------------------------------------


def test_raises_on_empty_writers(tmp_path: Path) -> None:
    p = _write_profile(tmp_path, {**_MINIMAL_PROFILE, "writers": []})
    with pytest.raises(GenerateProfileError, match="writers"):
        load_generate_profile(p)


def test_raises_on_duplicate_writer_ids(tmp_path: Path) -> None:
    p = _write_profile(tmp_path, {**_MINIMAL_PROFILE, "writers": [_MINIMAL_WRITER, _MINIMAL_WRITER]})
    with pytest.raises(GenerateProfileError, match="duplicate writer_id"):
        load_generate_profile(p)


def test_raises_on_duplicate_entry_ids_across_writers(tmp_path: Path) -> None:
    writer2 = {**_MINIMAL_WRITER, "writer_id": "w2"}
    p = _write_profile(tmp_path, {**_MINIMAL_PROFILE, "writers": [_MINIMAL_WRITER, writer2]})
    with pytest.raises(GenerateProfileError, match="entry_id"):
        load_generate_profile(p)


def test_raises_on_blank_writer_id(tmp_path: Path) -> None:
    bad = {**_MINIMAL_WRITER, "writer_id": "  "}
    p = _write_profile(tmp_path, {**_MINIMAL_PROFILE, "writers": [bad]})
    with pytest.raises(GenerateProfileError, match="writer_id"):
        load_generate_profile(p)


def test_raises_on_empty_scans(tmp_path: Path) -> None:
    bad = {**_MINIMAL_WRITER, "scans": []}
    p = _write_profile(tmp_path, {**_MINIMAL_PROFILE, "writers": [bad]})
    with pytest.raises(GenerateProfileError, match="scans"):
        load_generate_profile(p)


# ---------------------------------------------------------------------------
# glyph validation
# ---------------------------------------------------------------------------


def test_raises_on_non_hebrew_letter(tmp_path: Path) -> None:
    bad_glyph = {**_MINIMAL_GLYPH, "letter": "A"}
    scan = {"entry_id": "e__s__p0001", "glyphs": [bad_glyph]}
    p = _write_profile(tmp_path, {**_MINIMAL_PROFILE, "writers": [{**_MINIMAL_WRITER, "scans": [scan]}]})
    with pytest.raises(GenerateProfileError, match="Hebrew character"):
        load_generate_profile(p)


def test_raises_on_multi_char_letter(tmp_path: Path) -> None:
    bad_glyph = {**_MINIMAL_GLYPH, "letter": "אב"}
    scan = {"entry_id": "e__s__p0001", "glyphs": [bad_glyph]}
    p = _write_profile(tmp_path, {**_MINIMAL_PROFILE, "writers": [{**_MINIMAL_WRITER, "scans": [scan]}]})
    with pytest.raises(GenerateProfileError, match="Hebrew character"):
        load_generate_profile(p)


def test_raises_on_negative_x(tmp_path: Path) -> None:
    bad_glyph = {**_MINIMAL_GLYPH, "x": -1}
    scan = {"entry_id": "e__s__p0001", "glyphs": [bad_glyph]}
    p = _write_profile(tmp_path, {**_MINIMAL_PROFILE, "writers": [{**_MINIMAL_WRITER, "scans": [scan]}]})
    with pytest.raises(GenerateProfileError, match="≥ 0"):
        load_generate_profile(p)


def test_raises_on_zero_width(tmp_path: Path) -> None:
    bad_glyph = {**_MINIMAL_GLYPH, "width": 0}
    scan = {"entry_id": "e__s__p0001", "glyphs": [bad_glyph]}
    p = _write_profile(tmp_path, {**_MINIMAL_PROFILE, "writers": [{**_MINIMAL_WRITER, "scans": [scan]}]})
    with pytest.raises(GenerateProfileError, match="≥ 1"):
        load_generate_profile(p)


@pytest.mark.parametrize("letter", ["א", "ב", "ג", "ת", "ך", "ם", "ן", "ף", "ץ"])
def test_accepts_all_hebrew_letter_forms(tmp_path: Path, letter: str) -> None:
    glyph = {**_MINIMAL_GLYPH, "letter": letter}
    scan = {"entry_id": "e__s__p0001", "glyphs": [glyph]}
    p = _write_profile(tmp_path, {**_MINIMAL_PROFILE, "writers": [{**_MINIMAL_WRITER, "scans": [scan]}]})
    profile, _ = load_generate_profile(p)
    assert profile.writers[0].scans[0].glyphs[0].letter == letter
