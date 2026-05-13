"""Tests for the writer attribution config loader and validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hletterscriptgen.attribution import (
    AttributionEntryMismatchError,
    AttributionLoadError,
    AttributionMethod,
    DuplicateEntryIdError,
    DuplicateWriterIdError,
    EmptyEntryIdsError,
    UnknownAttributionMethodError,
    WriterProfile,
    load_attribution,
    validate_attribution_against_entries,
)
from hletterscriptgen.upstream import (
    UpstreamEntry,
    UpstreamFile,
    UpstreamQuality,
    UpstreamRights,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "attribution"
PROFILE_PATH = FIXTURE_DIR / "writer_profile.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_entry(entry_id: str) -> UpstreamEntry:
    return UpstreamEntry(
        entry_id=entry_id,
        source_id="fixture__source",
        creators=(),
        files=(
            UpstreamFile(
                role="original",
                local_path=None,
                sha256=None,
                mime_type=None,
                width_px=None,
                height_px=None,
            ),
        ),
        rights=UpstreamRights(
            license_expression="CC0-1.0",
            commercial_use_allowed=True,
            derivatives_allowed=True,
            scan_redistribution_allowed=True,
            verification_status="primary_page_checked",
        ),
        quality=UpstreamQuality(usable_for_htr=True, legibility="high"),
    )


def _write_profile(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "profile.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Round-trip parse of the canonical fixture
# ---------------------------------------------------------------------------


def test_roundtrip_parse_fixture() -> None:
    profile = load_attribution(PROFILE_PATH)

    assert isinstance(profile, WriterProfile)
    assert profile.source_path == PROFILE_PATH
    assert profile.upstream_path == Path("../public-domain-hand-written-hebrew-scans")

    writers_by_id = {w.writer_id: w for w in profile.writers}
    assert set(writers_by_id) == {"writer_bialik", "writer_herzl"}

    bialik = writers_by_id["writer_bialik"]
    assert bialik.attribution_method == AttributionMethod.collection_metadata
    assert bialik.entry_ids == frozenset(
        {
            "commons__bialik_letter_safed_1927__p0001",
            "commons__bialik_letter_safed_1927__p0002",
        }
    )
    assert bialik.notes is not None

    herzl = writers_by_id["writer_herzl"]
    assert herzl.attribution_method == AttributionMethod.manual_review
    assert herzl.entry_ids == frozenset({"commons__herzl_diary_1897__p0001"})
    assert herzl.notes is None


def test_roundtrip_writers_are_immutable() -> None:
    profile = load_attribution(PROFILE_PATH)
    for wa in profile.writers:
        assert isinstance(wa.entry_ids, frozenset)


# ---------------------------------------------------------------------------
# load_attribution — error cases
# ---------------------------------------------------------------------------


def test_load_raises_on_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "profile.json"
    p.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(AttributionLoadError) as excinfo:
        load_attribution(p)
    assert excinfo.value.path == p


def test_load_raises_on_non_object_root(tmp_path: Path) -> None:
    p = _write_profile(tmp_path, [1, 2, 3])
    with pytest.raises(AttributionLoadError):
        load_attribution(p)


def test_load_raises_on_missing_upstream_path(tmp_path: Path) -> None:
    p = _write_profile(tmp_path, {"writers": []})
    with pytest.raises(AttributionLoadError):
        load_attribution(p)


def test_load_raises_on_non_list_writers(tmp_path: Path) -> None:
    p = _write_profile(tmp_path, {"upstream_path": "/some/path", "writers": "oops"})
    with pytest.raises(AttributionLoadError):
        load_attribution(p)


def test_load_raises_duplicate_writer_id(tmp_path: Path) -> None:
    data = {
        "upstream_path": "/some/path",
        "writers": [
            {
                "writer_id": "writer_a",
                "attribution_method": "manual_review",
                "entry_ids": ["entry__001"],
            },
            {
                "writer_id": "writer_a",
                "attribution_method": "collection_metadata",
                "entry_ids": ["entry__002"],
            },
        ],
    }
    p = _write_profile(tmp_path, data)
    with pytest.raises(DuplicateWriterIdError) as excinfo:
        load_attribution(p)
    assert excinfo.value.writer_id == "writer_a"
    assert excinfo.value.path == p


def test_load_raises_duplicate_entry_id_across_writers(tmp_path: Path) -> None:
    data = {
        "upstream_path": "/some/path",
        "writers": [
            {
                "writer_id": "writer_a",
                "attribution_method": "manual_review",
                "entry_ids": ["shared__entry__p0001"],
            },
            {
                "writer_id": "writer_b",
                "attribution_method": "manual_review",
                "entry_ids": ["shared__entry__p0001"],
            },
        ],
    }
    p = _write_profile(tmp_path, data)
    with pytest.raises(DuplicateEntryIdError) as excinfo:
        load_attribution(p)
    assert excinfo.value.entry_id == "shared__entry__p0001"
    assert set([excinfo.value.first_writer, excinfo.value.second_writer]) == {
        "writer_a",
        "writer_b",
    }


def test_load_raises_empty_entry_ids(tmp_path: Path) -> None:
    data = {
        "upstream_path": "/some/path",
        "writers": [
            {
                "writer_id": "writer_a",
                "attribution_method": "manual_review",
                "entry_ids": [],
            }
        ],
    }
    p = _write_profile(tmp_path, data)
    with pytest.raises(EmptyEntryIdsError) as excinfo:
        load_attribution(p)
    assert excinfo.value.writer_id == "writer_a"


def test_load_raises_missing_entry_ids_key(tmp_path: Path) -> None:
    data = {
        "upstream_path": "/some/path",
        "writers": [
            {
                "writer_id": "writer_a",
                "attribution_method": "manual_review",
            }
        ],
    }
    p = _write_profile(tmp_path, data)
    with pytest.raises(EmptyEntryIdsError):
        load_attribution(p)


def test_load_raises_unknown_attribution_method(tmp_path: Path) -> None:
    data = {
        "upstream_path": "/some/path",
        "writers": [
            {
                "writer_id": "writer_a",
                "attribution_method": "psychic_vibes",
                "entry_ids": ["entry__001"],
            }
        ],
    }
    p = _write_profile(tmp_path, data)
    with pytest.raises(UnknownAttributionMethodError) as excinfo:
        load_attribution(p)
    assert excinfo.value.writer_id == "writer_a"
    assert excinfo.value.value == "psychic_vibes"


def test_load_raises_missing_writer_id(tmp_path: Path) -> None:
    data = {
        "upstream_path": "/some/path",
        "writers": [
            {
                "attribution_method": "manual_review",
                "entry_ids": ["entry__001"],
            }
        ],
    }
    p = _write_profile(tmp_path, data)
    with pytest.raises(AttributionLoadError):
        load_attribution(p)


# ---------------------------------------------------------------------------
# validate_attribution_against_entries
# ---------------------------------------------------------------------------


def test_validate_passes_when_all_ids_known(tmp_path: Path) -> None:
    profile = load_attribution(PROFILE_PATH)
    entries = [
        _minimal_entry("commons__bialik_letter_safed_1927__p0001"),
        _minimal_entry("commons__bialik_letter_safed_1927__p0002"),
        _minimal_entry("commons__herzl_diary_1897__p0001"),
    ]
    validate_attribution_against_entries(profile, entries)  # must not raise


def test_validate_passes_with_extra_upstream_entries(tmp_path: Path) -> None:
    profile = load_attribution(PROFILE_PATH)
    entries = [
        _minimal_entry("commons__bialik_letter_safed_1927__p0001"),
        _minimal_entry("commons__bialik_letter_safed_1927__p0002"),
        _minimal_entry("commons__herzl_diary_1897__p0001"),
        _minimal_entry("commons__extra_entry__p0001"),  # not attributed, that's fine
    ]
    validate_attribution_against_entries(profile, entries)  # must not raise


def test_validate_raises_on_unknown_entry_id(tmp_path: Path) -> None:
    data = {
        "upstream_path": "/some/path",
        "writers": [
            {
                "writer_id": "writer_a",
                "attribution_method": "manual_review",
                "entry_ids": ["known__entry__p0001", "ghost__entry__p0001"],
            }
        ],
    }
    p = _write_profile(tmp_path, data)
    profile = load_attribution(p)
    entries = [_minimal_entry("known__entry__p0001")]
    with pytest.raises(AttributionEntryMismatchError) as excinfo:
        validate_attribution_against_entries(profile, entries)
    assert "ghost__entry__p0001" in excinfo.value.unknown_ids
    assert excinfo.value.path == p


def test_validate_reports_all_unknown_ids(tmp_path: Path) -> None:
    data = {
        "upstream_path": "/some/path",
        "writers": [
            {
                "writer_id": "writer_a",
                "attribution_method": "manual_review",
                "entry_ids": ["ghost__a__p0001", "ghost__b__p0001"],
            }
        ],
    }
    p = _write_profile(tmp_path, data)
    profile = load_attribution(p)
    with pytest.raises(AttributionEntryMismatchError) as excinfo:
        validate_attribution_against_entries(profile, [])
    assert excinfo.value.unknown_ids == frozenset(
        {"ghost__a__p0001", "ghost__b__p0001"}
    )
