"""Tests for the upstream loader, eligibility gate, and pin helper."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hletterscriptgen.upstream import (
    UpstreamCheckoutDirtyError,
    UpstreamDetachedHeadError,
    UpstreamEntry,
    UpstreamLoadError,
    explain_ineligible,
    is_eligible,
    load_entries,
    upstream_pin_from_checkout,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "upstream"
ENTRIES_PATH = FIXTURE_DIR / "entries.jsonl"


@pytest.fixture(scope="module")
def entries_by_id() -> dict[str, UpstreamEntry]:
    return {entry.entry_id: entry for entry in load_entries(ENTRIES_PATH)}


# --- load_entries ------------------------------------------------------------


def test_load_entries_reads_all_records(entries_by_id: dict[str, UpstreamEntry]) -> None:
    assert set(entries_by_id) == {
        "fixture__eligible_pdm__p0001",
        "fixture__eligible_cc_by_sa__p0001",
        "fixture__reject_unusable__p0001",
        "fixture__reject_unverified__p0001",
    }


def test_load_entries_parses_nested_shapes(entries_by_id: dict[str, UpstreamEntry]) -> None:
    entry = entries_by_id["fixture__eligible_cc_by_sa__p0001"]
    assert entry.source_id == "fixture__eligible_cc_by_sa"
    assert entry.creators[0].name == "Example Writer"
    assert entry.creators[0].authority_url == "https://example.org/authority/1"
    assert entry.creators[0].death_year is None
    assert entry.files[0].role == "original"
    assert entry.files[0].sha256 == "0" * 63 + "2"
    assert entry.files[0].width_px == 1200
    assert entry.rights.license_expression == "CC-BY-SA-4.0"
    assert entry.rights.verification_status == "primary_page_checked"
    assert entry.quality.usable_for_htr is True
    assert entry.quality.legibility == "medium"


def test_load_entries_skips_blank_lines(tmp_path: Path) -> None:
    target = tmp_path / "entries.jsonl"
    target.write_text(
        "\n"
        '   \n'
        '{"entry_id":"a__b__p0001","source_id":"a__b","creators":[],"files":[],'
        '"rights":{"verification_status":"primary_page_checked"},'
        '"quality":{"legibility":"high"}}\n'
        "\n",
        encoding="utf-8",
    )
    entries = list(load_entries(target))
    assert len(entries) == 1
    assert entries[0].entry_id == "a__b__p0001"


def test_load_entries_raises_on_malformed_json(tmp_path: Path) -> None:
    target = tmp_path / "entries.jsonl"
    target.write_text(
        '{"entry_id":"a__b__p0001","source_id":"a__b","creators":[],"files":[],'
        '"rights":{"verification_status":"primary_page_checked"},'
        '"quality":{"legibility":"high"}}\n'
        "{not valid json\n",
        encoding="utf-8",
    )
    with pytest.raises(UpstreamLoadError) as excinfo:
        list(load_entries(target))
    assert excinfo.value.line_number == 2
    assert excinfo.value.path == target


def test_load_entries_raises_on_missing_required_field(tmp_path: Path) -> None:
    target = tmp_path / "entries.jsonl"
    target.write_text(
        '{"entry_id":"a__b__p0001"}\n',
        encoding="utf-8",
    )
    with pytest.raises(UpstreamLoadError) as excinfo:
        list(load_entries(target))
    assert excinfo.value.line_number == 1


# --- eligibility -------------------------------------------------------------


@pytest.mark.parametrize(
    "entry_id",
    ["fixture__eligible_pdm__p0001", "fixture__eligible_cc_by_sa__p0001"],
)
def test_eligible_entries_pass(
    entries_by_id: dict[str, UpstreamEntry], entry_id: str
) -> None:
    entry = entries_by_id[entry_id]
    assert is_eligible(entry)
    assert explain_ineligible(entry) == []


def test_reject_unusable_for_htr(entries_by_id: dict[str, UpstreamEntry]) -> None:
    entry = entries_by_id["fixture__reject_unusable__p0001"]
    assert not is_eligible(entry)
    reasons = explain_ineligible(entry)
    assert any("usable_for_htr" in r for r in reasons)


def test_reject_unverified_status(entries_by_id: dict[str, UpstreamEntry]) -> None:
    entry = entries_by_id["fixture__reject_unverified__p0001"]
    assert not is_eligible(entry)
    reasons = explain_ineligible(entry)
    assert any("verification_status" in r for r in reasons)


# --- upstream_pin_from_checkout ----------------------------------------------


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def _init_repo(path: Path, remote_url: str) -> str:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")
    _git(path, "remote", "add", "origin", remote_url)
    (path / "README.md").write_text("hi\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "init")
    rev = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return rev


def test_pin_returns_repo_and_revision(tmp_path: Path) -> None:
    repo = tmp_path / "upstream"
    rev = _init_repo(repo, "https://github.com/HeOCR/public-domain-hand-written-hebrew-scans.git")
    assert upstream_pin_from_checkout(repo) == (
        "HeOCR/public-domain-hand-written-hebrew-scans",
        rev,
    )


def test_pin_refuses_dirty_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "upstream"
    _init_repo(repo, "git@github.com:HeOCR/public-domain-hand-written-hebrew-scans.git")
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(UpstreamCheckoutDirtyError):
        upstream_pin_from_checkout(repo)


def test_pin_refuses_detached_head(tmp_path: Path) -> None:
    repo = tmp_path / "upstream"
    rev = _init_repo(repo, "https://github.com/HeOCR/foo.git")
    _git(repo, "checkout", "--detach", rev)
    with pytest.raises(UpstreamDetachedHeadError):
        upstream_pin_from_checkout(repo)


@pytest.mark.parametrize(
    "remote_url",
    [
        "https://github.com/HeOCR/foo.git",
        "https://github.com/HeOCR/foo",
        "git@github.com:HeOCR/foo.git",
        "ssh://git@github.com/HeOCR/foo.git",
    ],
)
def test_pin_normalizes_remote_url(tmp_path: Path, remote_url: str) -> None:
    repo = tmp_path / f"upstream_{abs(hash(remote_url))}"
    _init_repo(repo, remote_url)
    repo_name, _ = upstream_pin_from_checkout(repo)
    assert repo_name == "HeOCR/foo"
