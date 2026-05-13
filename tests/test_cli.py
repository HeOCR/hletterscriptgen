"""CLI smoke checks. In-process via cli.main(); one subprocess pin."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from hletterscriptgen import __version__
from hletterscriptgen.cli import (
    EXIT_INPUT_ERROR,
    EXIT_NOT_IMPLEMENTED,
    EXIT_OK,
    EXIT_VALIDATION_FAILED,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "letter_set" / "writer_example.json"
UPSTREAM_ENTRIES = Path(__file__).resolve().parent / "fixtures" / "upstream" / "entries.jsonl"
UPSTREAM_ENTRIES_ALL_ELIGIBLE = (
    Path(__file__).resolve().parent / "fixtures" / "upstream" / "entries_all_eligible.jsonl"
)


def test_version_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["version"])
    assert code == EXIT_OK
    assert capsys.readouterr().out.strip() == __version__


def test_schema_subcommand_json(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["schema", "--format", "json"])
    assert code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_id"] == "letter_set.v1"


def test_validate_subcommand_passes_on_example(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["validate", str(EXAMPLE), "--format", "json"])
    assert code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["error_count"] == 0


def test_validate_subcommand_fails_on_bad_doc(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "letter_set.v1"}), encoding="utf-8")
    code = main(["validate", str(bad), "--format", "json"])
    assert code == EXIT_VALIDATION_FAILED
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error_count"] >= 1
    assert all("kind" in err for err in payload["errors"])


def test_generate_subcommand_exits_not_implemented(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["generate"])
    assert code == EXIT_NOT_IMPLEMENTED
    assert EXIT_NOT_IMPLEMENTED == 69
    assert "not yet implemented" in capsys.readouterr().err


def test_check_eligible_text_mixed(capsys: pytest.CaptureFixture[str]) -> None:
    """Fixture has 2 eligible and 2 ineligible entries → exit 1, correct lines with reasons."""
    code = main(["check-eligible", str(UPSTREAM_ENTRIES)])
    assert code == EXIT_VALIDATION_FAILED
    out = capsys.readouterr().out
    entry_lines = {
        ln.split()[1].rstrip(":"): ln
        for ln in out.splitlines()
        if ln.startswith(("PASS ", "FAIL "))
    }
    assert entry_lines["fixture__eligible_pdm__p0001"] == "PASS fixture__eligible_pdm__p0001"
    cc_by_sa = "fixture__eligible_cc_by_sa__p0001"
    assert entry_lines[cc_by_sa] == f"PASS {cc_by_sa}"
    unusable = entry_lines["fixture__reject_unusable__p0001"]
    assert unusable.startswith("FAIL fixture__reject_unusable__p0001: ")
    assert "usable_for_htr" in unusable
    unverified = entry_lines["fixture__reject_unverified__p0001"]
    assert unverified.startswith("FAIL fixture__reject_unverified__p0001: ")
    assert "verification_status" in unverified
    assert "FAIL: 2/4 entries ineligible" in out


def test_check_eligible_json_mixed(capsys: pytest.CaptureFixture[str]) -> None:
    """JSON output for mixed fixture has correct shape and counts."""
    code = main(["check-eligible", str(UPSTREAM_ENTRIES), "--format", "json"])
    assert code == EXIT_VALIDATION_FAILED
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["total"] == 4
    assert payload["eligible"] == 2
    assert payload["ineligible"] == 2
    assert payload["path"] == str(UPSTREAM_ENTRIES)
    by_id = {e["entry_id"]: e for e in payload["entries"]}
    assert by_id["fixture__eligible_pdm__p0001"]["eligible"] is True
    assert by_id["fixture__eligible_pdm__p0001"]["reasons"] == []
    assert by_id["fixture__reject_unusable__p0001"]["eligible"] is False
    assert len(by_id["fixture__reject_unusable__p0001"]["reasons"]) >= 1


def test_check_eligible_json_key_order(capsys: pytest.CaptureFixture[str]) -> None:
    """JSON output puts 'ok' first so the primary signal is immediately visible."""
    main(["check-eligible", str(UPSTREAM_ENTRIES), "--format", "json"])
    raw = capsys.readouterr().out
    keys = [k for k in json.loads(raw) if k != "entries"]
    assert keys[0] == "ok"


def test_check_eligible_all_pass(capsys: pytest.CaptureFixture[str]) -> None:
    """All-eligible fixture → exit 0, PASS line, OK summary."""
    code = main(["check-eligible", str(UPSTREAM_ENTRIES_ALL_ELIGIBLE)])
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "PASS fixture__eligible_only__p0001" in out
    assert "OK: 1/1 entries eligible" in out


def test_check_eligible_json_all_pass(capsys: pytest.CaptureFixture[str]) -> None:
    """JSON output when all entries are eligible has ok=true."""
    code = main(["check-eligible", str(UPSTREAM_ENTRIES_ALL_ELIGIBLE), "--format", "json"])
    assert code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["total"] == 1
    assert payload["eligible"] == 1
    assert payload["ineligible"] == 0


def test_check_eligible_empty_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Empty file (zero entries) → exit 0, zero-count OK summary. Pins the edge-case behaviour."""
    target = tmp_path / "empty.jsonl"
    target.write_text("", encoding="utf-8")
    code = main(["check-eligible", str(target)])
    assert code == EXIT_OK
    assert "OK: 0/0 entries eligible" in capsys.readouterr().out


def test_check_eligible_load_error_exits_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Malformed JSONL line → message on stderr, EXIT_INPUT_ERROR."""
    target = tmp_path / "bad.jsonl"
    target.write_text("{not valid json\n", encoding="utf-8")
    code = main(["check-eligible", str(target)])
    assert code == EXIT_INPUT_ERROR
    assert capsys.readouterr().err.strip() != ""


def test_module_entry_point_runs() -> None:
    """One real-subprocess smoke to prove `python -m hletterscriptgen` works."""
    proc = subprocess.run(
        [sys.executable, "-m", "hletterscriptgen", "version"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert proc.returncode == EXIT_OK, proc.stderr
    assert proc.stdout.strip() == __version__
