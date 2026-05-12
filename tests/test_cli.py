"""CLI smoke checks. In-process via cli.main(); one subprocess pin."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from hletterscriptgen import __version__
from hletterscriptgen.cli import (
    EXIT_NOT_IMPLEMENTED,
    EXIT_OK,
    EXIT_VALIDATION_FAILED,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "letter_set" / "writer_example.json"


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
