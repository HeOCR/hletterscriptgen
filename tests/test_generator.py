"""End-to-end tests for the generator pipeline."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from hletterscriptgen.generate_profile import load_generate_profile  # noqa: E402
from hletterscriptgen.generator import GeneratorError, generate  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers — synthetic upstream checkout + scan
# ---------------------------------------------------------------------------

_ELIGIBLE_ENTRY = {
    "entry_id": "test__writer_a__p0001",
    "source_id": "test__writer_a",
    "creators": [{"name": "Test Author", "role": "writer", "death_year": 1900}],
    "files": [
        {
            "role": "original",
            "local_path": "data/scans/test__writer_a/p0001.png",
            "sha256": "0" * 64,
            "mime_type": "image/png",
            "width_px": 100,
            "height_px": 100,
        }
    ],
    "rights": {
        "license_expression": "PDM-1.0",
        "commercial_use_allowed": True,
        "derivatives_allowed": True,
        "scan_redistribution_allowed": True,
        "verification_status": "primary_page_checked",
    },
    "quality": {"usable_for_htr": True, "legibility": "high"},
}


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def _make_upstream_checkout(tmp_path: Path) -> Path:
    """Create a minimal upstream git repo with one eligible entry and a scan."""
    repo = tmp_path / "upstream"
    repo.mkdir()

    # Initialise git repo
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "remote", "add", "origin", "https://github.com/HeOCR/public-domain-hand-written-hebrew-scans.git")

    # entries.jsonl
    index_dir = repo / "data" / "index"
    index_dir.mkdir(parents=True)
    (index_dir / "entries.jsonl").write_text(
        json.dumps(_ELIGIBLE_ENTRY) + "\n", encoding="utf-8"
    )

    # Synthetic scan PNG: white 100x100 with two black 20x20 blobs
    scan_dir = repo / "data" / "scans" / "test__writer_a"
    scan_dir.mkdir(parents=True)
    img = np.full((100, 100, 3), 255, dtype=np.uint8)
    img[5:25, 5:25] = 0    # blob at (5,5) 20x20
    img[5:25, 35:55] = 0   # blob at (35,5) 20x20
    cv2.imwrite(str(scan_dir / "p0001.png"), img)

    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def _make_profile(tmp_path: Path, upstream: Path) -> Path:
    """Write a generation profile that uses the upstream checkout."""
    profile_data = {
        "upstream_checkout": str(upstream),
        "writers": [
            {
                "writer_id": "writer_test_a",
                "attribution_method": "manual_review",
                "scans": [
                    {
                        "entry_id": "test__writer_a__p0001",
                        "glyphs": [
                            {"letter": "א", "x": 5, "y": 5, "width": 20, "height": 20},
                            {"letter": "ב", "x": 35, "y": 5, "width": 20, "height": 20},
                        ],
                    }
                ],
            }
        ],
    }
    p = tmp_path / "profile.json"
    p.write_text(json.dumps(profile_data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# generate — happy path
# ---------------------------------------------------------------------------


def test_generate_produces_letter_set_json(tmp_path: Path) -> None:
    upstream = _make_upstream_checkout(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)
    output_dir = tmp_path / "out"

    profile = load_generate_profile(profile_path)
    paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    assert len(paths) == 1
    letter_set_path = paths[0]
    assert letter_set_path.exists()
    assert letter_set_path.name == "letter_set.json"


def test_generate_letter_set_validates(tmp_path: Path) -> None:
    from hletterscriptgen.validation import validate_document

    upstream = _make_upstream_checkout(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)
    output_dir = tmp_path / "out"

    profile = load_generate_profile(profile_path)
    paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    result = validate_document(doc)
    assert result.ok, [i.format() for i in result.issues]


def test_generate_letter_set_content(tmp_path: Path) -> None:
    upstream = _make_upstream_checkout(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)
    output_dir = tmp_path / "out"

    profile = load_generate_profile(profile_path)
    paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    assert doc["schema_version"] == "letter_set.v1"
    assert doc["writer_id"] == "writer_test_a"
    assert doc["upstream"]["repo"] == "HeOCR/public-domain-hand-written-hebrew-scans"
    assert doc["generator"]["name"] == "hletterscriptgen"
    # Both annotated letters must appear
    assert "א" in doc["letters"]
    assert "ב" in doc["letters"]
    assert len(doc["letters"]["א"]) == 1
    assert len(doc["letters"]["ב"]) == 1


def test_generate_writes_glyph_pngs(tmp_path: Path) -> None:
    upstream = _make_upstream_checkout(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)
    output_dir = tmp_path / "out"

    profile = load_generate_profile(profile_path)
    paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    writer_dir = paths[0].parent

    for letter, variants in doc["letters"].items():
        for variant in variants:
            asset = writer_dir / variant["asset_path"]
            assert asset.exists(), f"asset missing: {asset}"
            assert asset.read_bytes()[:4] == b"\x89PNG"


def test_generate_checksum_matches_png(tmp_path: Path) -> None:
    import hashlib

    upstream = _make_upstream_checkout(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)
    output_dir = tmp_path / "out"

    profile = load_generate_profile(profile_path)
    paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    writer_dir = paths[0].parent

    for variants in doc["letters"].values():
        for variant in variants:
            png_bytes = (writer_dir / variant["asset_path"]).read_bytes()
            assert hashlib.sha256(png_bytes).hexdigest() == variant["checksum_sha256"]


def test_generate_is_deterministic(tmp_path: Path) -> None:
    """Same profile + upstream + generated_at → bit-identical output."""
    upstream = _make_upstream_checkout(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)

    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"

    profile = load_generate_profile(profile_path)
    ts = "2025-06-01T12:00:00+00:00"
    paths1 = generate(profile, out1, generated_at=ts)
    paths2 = generate(profile, out2, generated_at=ts)

    doc1 = json.loads(paths1[0].read_text(encoding="utf-8"))
    doc2 = json.loads(paths2[0].read_text(encoding="utf-8"))
    assert doc1 == doc2

    # PNG bytes should be identical too
    for variants in doc1["letters"].values():
        for variant in variants:
            b1 = (out1 / "writer_test_a" / variant["asset_path"]).read_bytes()
            b2 = (out2 / "writer_test_a" / variant["asset_path"]).read_bytes()
            assert b1 == b2


def test_generate_raises_when_no_glyphs_extracted(tmp_path: Path) -> None:
    """A profile whose scans all have missing files should raise GeneratorError."""
    upstream = _make_upstream_checkout(tmp_path)
    # Point the profile at a non-existent entry_id
    profile_data = {
        "upstream_checkout": str(upstream),
        "writers": [
            {
                "writer_id": "writer_test_a",
                "attribution_method": "manual_review",
                "scans": [
                    {
                        "entry_id": "does__not__exist__p0001",
                        "glyphs": [{"letter": "א", "x": 0, "y": 0, "width": 20, "height": 20}],
                    }
                ],
            }
        ],
    }
    p = tmp_path / "profile.json"
    p.write_text(json.dumps(profile_data), encoding="utf-8")

    profile = load_generate_profile(p)
    with pytest.raises(GeneratorError, match="no glyphs"):
        generate(profile, tmp_path / "out", generated_at="2025-01-01T00:00:00+00:00")


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_generate_exits_ok(tmp_path: Path) -> None:
    from hletterscriptgen.cli import main

    upstream = _make_upstream_checkout(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)
    output_dir = tmp_path / "out"

    rc = main([
        "generate",
        "--profile", str(profile_path),
        "--output", str(output_dir),
        "--generated-at", "2025-01-01T00:00:00+00:00",
    ])
    assert rc == 0
    assert (output_dir / "writer_test_a" / "letter_set.json").exists()


def test_cli_scan_blobs_exits_ok(tmp_path: Path) -> None:
    from hletterscriptgen.cli import main

    img = np.full((100, 100, 3), 255, dtype=np.uint8)
    img[10:30, 10:30] = 0
    scan = tmp_path / "scan.png"
    cv2.imwrite(str(scan), img)

    rc = main(["scan-blobs", str(scan)])
    assert rc == 0


def test_cli_scan_blobs_text_format(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from hletterscriptgen.cli import main

    img = np.full((100, 100, 3), 255, dtype=np.uint8)
    img[10:30, 10:30] = 0
    scan = tmp_path / "scan.png"
    cv2.imwrite(str(scan), img)

    rc = main(["scan-blobs", str(scan), "--format", "text"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "blob" in out
    assert "detected" in out


# ---------------------------------------------------------------------------
# Mock-based tests — document assembly without cv2 I/O
# ---------------------------------------------------------------------------

# A minimal valid PNG (1x1 white pixel) used as a fake crop result.
_FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_upstream_checkout_no_cv2(tmp_path: Path) -> Path:
    """Create a minimal upstream git repo with a stub scan file (no cv2 needed)."""
    repo = tmp_path / "upstream_nodeps"
    repo.mkdir()

    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "remote", "add", "origin", "https://github.com/HeOCR/public-domain-hand-written-hebrew-scans.git")

    index_dir = repo / "data" / "index"
    index_dir.mkdir(parents=True)
    (index_dir / "entries.jsonl").write_text(
        json.dumps(_ELIGIBLE_ENTRY) + "\n", encoding="utf-8"
    )

    # Write any bytes — binarize_scan is mocked and won't read this.
    scan_dir = repo / "data" / "scans" / "test__writer_a"
    scan_dir.mkdir(parents=True)
    (scan_dir / "p0001.png").write_bytes(b"STUB")

    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def test_generate_document_structure_mocked(tmp_path: Path) -> None:
    """Document assembly, validation, and file writing with mocked cv2 calls."""
    upstream = _make_upstream_checkout_no_cv2(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)
    output_dir = tmp_path / "out"

    profile = load_generate_profile(profile_path)
    fake_binary = MagicMock()

    with patch("hletterscriptgen.generator.binarize_scan", return_value=fake_binary):
        with patch("hletterscriptgen.generator.crop_binary", return_value=_FAKE_PNG):
            paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    assert len(paths) == 1
    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    assert doc["schema_version"] == "letter_set.v1"
    assert doc["writer_id"] == "writer_test_a"
    assert "א" in doc["letters"]
    assert "ב" in doc["letters"]


def test_generate_mocked_validates(tmp_path: Path) -> None:
    """Generated document must pass schema validation even with mocked crops."""
    from hletterscriptgen.validation import validate_document

    upstream = _make_upstream_checkout_no_cv2(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)
    output_dir = tmp_path / "out"

    profile = load_generate_profile(profile_path)
    with patch("hletterscriptgen.generator.binarize_scan", return_value=MagicMock()):
        with patch("hletterscriptgen.generator.crop_binary", return_value=_FAKE_PNG):
            paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    result = validate_document(doc)
    assert result.ok, [i.format() for i in result.issues]


def test_generate_mocked_writes_png_assets(tmp_path: Path) -> None:
    """PNG assets must exist on disk with correct PNG magic bytes."""
    upstream = _make_upstream_checkout_no_cv2(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)
    output_dir = tmp_path / "out"

    profile = load_generate_profile(profile_path)
    with patch("hletterscriptgen.generator.binarize_scan", return_value=MagicMock()):
        with patch("hletterscriptgen.generator.crop_binary", return_value=_FAKE_PNG):
            paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    writer_dir = paths[0].parent
    for variants in doc["letters"].values():
        for variant in variants:
            asset = writer_dir / variant["asset_path"]
            assert asset.exists()
            assert asset.read_bytes()[:4] == b"\x89PNG"


def test_generate_mocked_glyph_notes_in_variant(tmp_path: Path) -> None:
    """A glyph annotation with notes must propagate the notes to its variant."""
    upstream = _make_upstream_checkout_no_cv2(tmp_path)
    profile_data = {
        "upstream_checkout": str(upstream),
        "writers": [
            {
                "writer_id": "writer_test_a",
                "attribution_method": "manual_review",
                "scans": [
                    {
                        "entry_id": "test__writer_a__p0001",
                        "glyphs": [
                            {
                                "letter": "א",
                                "x": 5, "y": 5, "width": 20, "height": 20,
                                "notes": "this is a test note",
                            },
                        ],
                    }
                ],
            }
        ],
    }
    p = tmp_path / "profile.json"
    p.write_text(json.dumps(profile_data), encoding="utf-8")

    output_dir = tmp_path / "out"
    profile = load_generate_profile(p)
    with patch("hletterscriptgen.generator.binarize_scan", return_value=MagicMock()):
        with patch("hletterscriptgen.generator.crop_binary", return_value=_FAKE_PNG):
            paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    variant = doc["letters"]["א"][0]
    assert variant.get("notes") == "this is a test note"


def test_generate_mocked_config_hash_in_document(tmp_path: Path) -> None:
    """generator.config_hash in the output document must match profile.config_hash."""
    upstream = _make_upstream_checkout_no_cv2(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)
    output_dir = tmp_path / "out"

    profile = load_generate_profile(profile_path)
    with patch("hletterscriptgen.generator.binarize_scan", return_value=MagicMock()):
        with patch("hletterscriptgen.generator.crop_binary", return_value=_FAKE_PNG):
            paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    assert doc["generator"]["config_hash"] == profile.config_hash
