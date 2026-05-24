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

    with patch("hletterscriptgen.generator.binarize_scan", return_value=MagicMock()):
        with patch("hletterscriptgen.generator.crop_binary", return_value=_FAKE_PNG):
            with patch("hletterscriptgen.generator.compute_ink_ratio", return_value=0.3):
                with patch("hletterscriptgen.generator.compute_dhash", return_value=0):
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
            with patch("hletterscriptgen.generator.compute_ink_ratio", return_value=0.3):
                with patch("hletterscriptgen.generator.compute_dhash", return_value=0):
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
            with patch("hletterscriptgen.generator.compute_ink_ratio", return_value=0.3):
                with patch("hletterscriptgen.generator.compute_dhash", return_value=0):
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
            with patch("hletterscriptgen.generator.compute_ink_ratio", return_value=0.3):
                with patch("hletterscriptgen.generator.compute_dhash", return_value=0):
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
            with patch("hletterscriptgen.generator.compute_ink_ratio", return_value=0.3):
                with patch("hletterscriptgen.generator.compute_dhash", return_value=0):
                    paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    assert doc["generator"]["config_hash"] == profile.config_hash


# ---------------------------------------------------------------------------
# M4: quality metrics
# ---------------------------------------------------------------------------


def test_generate_variant_has_quality_ink_ratio(tmp_path: Path) -> None:
    """Every generated variant must carry a quality.ink_ratio in [0, 1]."""
    upstream = _make_upstream_checkout(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)
    output_dir = tmp_path / "out"

    profile = load_generate_profile(profile_path)
    paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    for variants in doc["letters"].values():
        for variant in variants:
            assert "quality" in variant, f"variant {variant['variant_id']!r} missing 'quality'"
            ink = variant["quality"]["ink_ratio"]
            assert isinstance(ink, float), f"ink_ratio must be float, got {type(ink)}"
            assert 0.0 <= ink <= 1.0, f"ink_ratio out of range: {ink}"


def test_generate_variant_ink_ratio_nonzero_for_solid_blobs(tmp_path: Path) -> None:
    """Solid black blobs should produce an ink_ratio > 0."""
    upstream = _make_upstream_checkout(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)
    output_dir = tmp_path / "out"

    profile = load_generate_profile(profile_path)
    paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    for variants in doc["letters"].values():
        for variant in variants:
            assert variant["quality"]["ink_ratio"] > 0.0


def test_generate_mocked_variant_has_quality(tmp_path: Path) -> None:
    """Mock path: quality.ink_ratio must still be present and valid."""
    upstream = _make_upstream_checkout_no_cv2(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)
    output_dir = tmp_path / "out"

    fake_binary = MagicMock()
    # compute_ink_ratio will call (crop > 0).sum() on the binary slice;
    # wire the mock so that expression returns 50 (out of 400 px).
    fake_binary.__getitem__ = MagicMock(return_value=MagicMock(**{"__gt__": MagicMock(return_value=MagicMock(**{"sum.return_value": 50}))}))  # noqa: E501

    profile = load_generate_profile(profile_path)
    with patch("hletterscriptgen.generator.binarize_scan", return_value=fake_binary):
        with patch("hletterscriptgen.generator.crop_binary", return_value=_FAKE_PNG):
            with patch("hletterscriptgen.generator.compute_ink_ratio", return_value=0.25):
                with patch("hletterscriptgen.generator.compute_dhash", return_value=0):
                    paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    for variants in doc["letters"].values():
        for variant in variants:
            assert variant["quality"]["ink_ratio"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# M4: near-duplicate deduplication
# ---------------------------------------------------------------------------


def test_generate_dedup_removes_near_duplicate(tmp_path: Path) -> None:
    """Two glyphs with identical dHash (Hamming 0) should collapse to one."""
    upstream = _make_upstream_checkout_no_cv2(tmp_path)

    # Two glyphs annotated on the same entry, same letter — will get identical
    # hashes because compute_dhash is patched to return the same value.
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
                            {"letter": "א", "x": 5, "y": 5, "width": 20, "height": 20},
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
            with patch("hletterscriptgen.generator.compute_ink_ratio", return_value=0.3):
                with patch("hletterscriptgen.generator.compute_dhash", return_value=42):
                    paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    # Both annotations had the same hash → dedup leaves exactly one variant
    assert len(doc["letters"]["א"]) == 1


def test_generate_dedup_keeps_higher_ink_ratio(tmp_path: Path) -> None:
    """When two near-dupes differ in ink_ratio, the higher one survives."""
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
                            {"letter": "א", "x": 5, "y": 5, "width": 20, "height": 20},
                            {"letter": "א", "x": 5, "y": 5, "width": 20, "height": 20},
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

    # First call returns 0.20, second returns 0.45 (better)
    ink_side_effect = [0.20, 0.45]

    with patch("hletterscriptgen.generator.binarize_scan", return_value=MagicMock()):
        with patch("hletterscriptgen.generator.crop_binary", return_value=_FAKE_PNG):
            with patch("hletterscriptgen.generator.compute_ink_ratio", side_effect=ink_side_effect):
                with patch("hletterscriptgen.generator.compute_dhash", return_value=0):
                    paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    assert len(doc["letters"]["א"]) == 1
    assert doc["letters"]["א"][0]["quality"]["ink_ratio"] == pytest.approx(0.45)


def test_generate_dedup_keeps_distinct_glyphs(tmp_path: Path) -> None:
    """Two glyphs with Hamming distance > threshold must both survive dedup."""
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
                            {"letter": "א", "x": 5, "y": 5, "width": 20, "height": 20},
                            {"letter": "א", "x": 35, "y": 5, "width": 20, "height": 20},
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

    # Hashes differ by >> 10 bits → both survive
    with patch("hletterscriptgen.generator.binarize_scan", return_value=MagicMock()):
        with patch("hletterscriptgen.generator.crop_binary", return_value=_FAKE_PNG):
            with patch("hletterscriptgen.generator.compute_ink_ratio", return_value=0.3):
                with patch(
                    "hletterscriptgen.generator.compute_dhash",
                    side_effect=[0x0000_0000_0000_0000, 0xFFFF_FFFF_FFFF_FFFF],
                ):
                    paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    assert len(doc["letters"]["א"]) == 2


def test_generate_variant_no_dhash_in_output(tmp_path: Path) -> None:
    """The internal _dhash key must not leak into the written letter_set.json."""
    upstream = _make_upstream_checkout_no_cv2(tmp_path)
    profile_path = _make_profile(tmp_path, upstream)
    output_dir = tmp_path / "out"

    profile = load_generate_profile(profile_path)
    with patch("hletterscriptgen.generator.binarize_scan", return_value=MagicMock()):
        with patch("hletterscriptgen.generator.crop_binary", return_value=_FAKE_PNG):
            with patch("hletterscriptgen.generator.compute_ink_ratio", return_value=0.3):
                with patch("hletterscriptgen.generator.compute_dhash", return_value=0):
                    paths = generate(profile, output_dir, generated_at="2025-01-01T00:00:00+00:00")

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    for variants in doc["letters"].values():
        for variant in variants:
            assert "_dhash" not in variant
