"""End-to-end tests for the generator pipeline."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from hletterscriptgen.generate_profile import load_generate_profile  # noqa: E402
from hletterscriptgen.generator import (  # noqa: E402
    GeneratorError,
    GeneratorWarning,
    _dedup_letter_variants,
    generate,
)

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
    _git(repo, "remote", "add", "origin", "https://github.com/HeOCR/hash.git")

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
    assert doc["upstream"]["repo"] == "HeOCR/hash"
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
    _git(repo, "remote", "add", "origin", "https://github.com/HeOCR/hash.git")

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
# _dedup_letter_variants — isolated unit tests
# ---------------------------------------------------------------------------

# Build a minimal variant dict that satisfies the function's expectations.
# Internal keys (_dhash, _png_bytes) must be present; schema keys are minimal.
def _v(
    vid: str,
    ink: float,
    dhash: int,
    *,
    entry_id: str = "e1",
    license_id: str = "PDM-1.0",
) -> dict[str, Any]:
    return {
        "_dhash": dhash,
        "_png_bytes": b"\x89PNG stub",
        "variant_id": vid,
        "asset_path": f"glyphs/א/{vid}.png",
        "checksum_sha256": "0" * 64,
        "image": {"width_px": 20, "height_px": 20, "format": "png"},
        "quality": {"ink_ratio": ink},
        "source": {
            "scan_entry_id": entry_id,
            "license": license_id,
            "bbox_in_source": {"x": 0, "y": 0, "width": 20, "height": 20},
        },
        "extracted_at": "2025-01-01T00:00:00+00:00",
    }


def test_dedup_single_variant_returned_unchanged() -> None:
    """A single variant survives dedup unmodified."""
    v = _v("v1", 0.3, dhash=0)
    result = _dedup_letter_variants([v])
    assert len(result) == 1
    assert result[0]["variant_id"] == "v1"
    assert result[0]["_dhash"] == 0  # caller strips; still present here


def test_dedup_identical_hashes_keeps_higher_ink_ratio() -> None:
    """Two variants with Hamming distance 0 collapse to one; higher ink wins."""
    low = _v("v-low", ink=0.20, dhash=0)
    high = _v("v-high", ink=0.45, dhash=0)
    result = _dedup_letter_variants([low, high])
    assert len(result) == 1
    assert result[0]["quality"]["ink_ratio"] == pytest.approx(0.45)
    assert result[0]["variant_id"] == "v-high"


def test_dedup_identical_hashes_first_wins_when_ink_equal_or_lower() -> None:
    """When the representative already has better ink, it is not replaced."""
    first = _v("v-first", ink=0.50, dhash=7)
    second = _v("v-second", ink=0.30, dhash=7)
    result = _dedup_letter_variants([first, second])
    assert len(result) == 1
    assert result[0]["variant_id"] == "v-first"


def test_dedup_distinct_hashes_both_survive() -> None:
    """Two variants with Hamming distance > threshold both survive."""
    a = _v("v-a", ink=0.3, dhash=0x0000_0000_0000_0000)
    b = _v("v-b", ink=0.3, dhash=0xFFFF_FFFF_FFFF_FFFF)
    result = _dedup_letter_variants([a, b])
    assert len(result) == 2


def test_dedup_threshold_boundary_at_exactly_threshold() -> None:
    """Hamming distance exactly equal to the threshold is still a near-dupe."""
    from hletterscriptgen.generator import _DEDUP_HAMMING_THRESHOLD

    # Build a hash that differs by exactly _DEDUP_HAMMING_THRESHOLD bits from 0.
    border_hash = (1 << _DEDUP_HAMMING_THRESHOLD) - 1  # lowest N bits set
    assert bin(border_hash).count("1") == _DEDUP_HAMMING_THRESHOLD

    a = _v("v-a", ink=0.3, dhash=0)
    b = _v("v-b", ink=0.4, dhash=border_hash)
    result = _dedup_letter_variants([a, b])
    assert len(result) == 1


def test_dedup_threshold_boundary_one_over_survives() -> None:
    """Hamming distance one above threshold is distinct; both variants survive."""
    from hletterscriptgen.generator import _DEDUP_HAMMING_THRESHOLD

    over_hash = (1 << (_DEDUP_HAMMING_THRESHOLD + 1)) - 1  # N+1 bits set
    assert bin(over_hash).count("1") == _DEDUP_HAMMING_THRESHOLD + 1

    a = _v("v-a", ink=0.3, dhash=0)
    b = _v("v-b", ink=0.3, dhash=over_hash)
    result = _dedup_letter_variants([a, b])
    assert len(result) == 2


def test_dedup_cluster_centre_preserved_prevents_drift() -> None:
    """Cluster centre hash must not drift when the representative is replaced.

    Scenario (hashes chosen so that |A-B| <= threshold but |A-C| > threshold,
    yet |B-C| <= threshold):

    - A processed first → cluster centre = A_hash.
    - B processed: near A → B replaces A (higher ink); centre stays A_hash.
    - C processed: compared against A_hash (not B_hash).
      |A-C| > threshold → C survives as a new cluster.

    Without the fix, C would be compared against B_hash, |B-C| <= threshold,
    and C would be incorrectly absorbed.
    """
    # A_hash = 0 (all zeros, 64 bits)
    # B_hash = 0xFF (8 bits set): hamming(A,B) = 8 <= 10 (near-dupe)
    # C_hash = 0xFFF (12 bits set): hamming(A,C) = 12 > 10 (distinct from A)
    #          but hamming(B,C) = hamming(0xFF, 0xFFF) = 4 <= 10 (near B)
    A_hash = 0x00
    B_hash = 0xFF        # 8 bits set; hamming(A,B)=8 <= 10
    C_hash = 0xFFF       # 12 bits set; hamming(A,C)=12 > 10; hamming(B,C)=4 <= 10

    a = _v("v-a", ink=0.20, dhash=A_hash)
    b = _v("v-b", ink=0.40, dhash=B_hash)  # better ink → replaces A in cluster
    c = _v("v-c", ink=0.30, dhash=C_hash)  # must survive as its own cluster

    result = _dedup_letter_variants([a, b, c])
    assert len(result) == 2, (
        "C should survive as a distinct cluster (|A-C|=12 > threshold), "
        "but the cluster centre drifted to B_hash and absorbed C"
    )
    ids = {r["variant_id"] for r in result}
    assert "v-b" in ids  # winner of first cluster
    assert "v-c" in ids  # distinct second cluster


def test_dedup_internal_keys_not_stripped() -> None:
    """_dedup_letter_variants must NOT strip _dhash or _png_bytes — that is the caller's job."""
    v = _v("v1", 0.3, dhash=42)
    result = _dedup_letter_variants([v])
    assert "_dhash" in result[0]
    assert "_png_bytes" in result[0]


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

    profile = load_generate_profile(profile_path)
    with patch("hletterscriptgen.generator.binarize_scan", return_value=MagicMock()):
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

    ts = "2025-01-01T00:00:00+00:00"
    with pytest.warns(GeneratorWarning, match="near-duplicate"):
        with patch("hletterscriptgen.generator.binarize_scan", return_value=MagicMock()):
            with patch("hletterscriptgen.generator.crop_binary", return_value=_FAKE_PNG):
                with patch("hletterscriptgen.generator.compute_ink_ratio", return_value=0.3):
                    with patch("hletterscriptgen.generator.compute_dhash", return_value=42):
                        paths = generate(profile, output_dir, generated_at=ts)

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

    ts = "2025-01-01T00:00:00+00:00"
    with pytest.warns(GeneratorWarning, match="near-duplicate"):
        with patch("hletterscriptgen.generator.binarize_scan", return_value=MagicMock()):
            with patch("hletterscriptgen.generator.crop_binary", return_value=_FAKE_PNG):
                with patch("hletterscriptgen.generator.compute_ink_ratio", side_effect=ink_side_effect):  # noqa: E501
                    with patch("hletterscriptgen.generator.compute_dhash", return_value=0):
                        paths = generate(profile, output_dir, generated_at=ts)

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
