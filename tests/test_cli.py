"""CLI smoke checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "letter_set" / "writer_example.json"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hletterscriptgen", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_version_subcommand() -> None:
    proc = _run_cli("version")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip()


def test_schema_subcommand_json() -> None:
    proc = _run_cli("schema", "--format", "json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema_id"] == "letter_set.v1"


def test_validate_subcommand_passes_on_example() -> None:
    proc = _run_cli("validate", str(EXAMPLE), "--format", "json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["error_count"] == 0


def test_validate_subcommand_fails_on_bad_doc(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "letter_set.v1"}), encoding="utf-8")
    proc = _run_cli("validate", str(bad), "--format", "json")
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["error_count"] >= 1
