"""Tests for the CCA glyph extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402 — after importorskip so this only runs with cv2

from hletterscriptgen.extractor import (  # noqa: E402
    MIN_GLYPH_PX,
    ExtractionError,
    Glyph,
    binarize_scan,
    compute_dhash,
    compute_ink_ratio,
    crop_glyph,
    extract_glyphs,
    hamming_distance,
)

# ---------------------------------------------------------------------------
# Synthetic image helpers
# ---------------------------------------------------------------------------


def _white_image(width: int, height: int) -> np.ndarray:  # type: ignore[type-arg]
    """Return a white (255) BGR image of the given dimensions."""
    return np.full((height, width, 3), 255, dtype=np.uint8)


def _draw_black_rect(
    img: np.ndarray,  # type: ignore[type-arg]
    x: int,
    y: int,
    w: int,
    h: int,
) -> None:
    """Draw a solid black rectangle on img (in-place)."""
    img[y : y + h, x : x + w] = 0


def _save_png(img: np.ndarray, path: Path) -> None:  # type: ignore[type-arg]
    cv2.imwrite(str(path), img)


# ---------------------------------------------------------------------------
# extract_glyphs
# ---------------------------------------------------------------------------


def test_extract_glyphs_detects_blobs(tmp_path: Path) -> None:
    """Two well-separated black rectangles on a white background."""
    img = _white_image(200, 100)
    _draw_black_rect(img, x=10, y=10, w=30, h=30)  # left blob
    _draw_black_rect(img, x=100, y=10, w=30, h=30)  # right blob
    scan = tmp_path / "scan.png"
    _save_png(img, scan)

    glyphs = extract_glyphs(scan)

    assert len(glyphs) == 2
    # Sorted right-to-left (larger x first) within the same y-row.
    assert glyphs[0].x > glyphs[1].x


def test_extract_glyphs_filters_small_blobs(tmp_path: Path) -> None:
    """Blobs below MIN_GLYPH_PX in either dimension should be dropped."""
    img = _white_image(200, 100)
    _draw_black_rect(img, x=10, y=10, w=MIN_GLYPH_PX, h=MIN_GLYPH_PX)  # exactly at floor
    _draw_black_rect(img, x=60, y=10, w=MIN_GLYPH_PX - 1, h=MIN_GLYPH_PX)  # too narrow
    _draw_black_rect(img, x=110, y=10, w=MIN_GLYPH_PX, h=MIN_GLYPH_PX - 1)  # too short
    scan = tmp_path / "scan.png"
    _save_png(img, scan)

    glyphs = extract_glyphs(scan)

    assert len(glyphs) == 1
    assert glyphs[0].x == 10


def test_extract_glyphs_respects_custom_min_dimension(tmp_path: Path) -> None:
    img = _white_image(200, 100)
    _draw_black_rect(img, x=10, y=10, w=10, h=10)
    _draw_black_rect(img, x=60, y=10, w=30, h=30)
    scan = tmp_path / "scan.png"
    _save_png(img, scan)

    glyphs_strict = extract_glyphs(scan, min_dimension=20)
    glyphs_loose = extract_glyphs(scan, min_dimension=8)

    assert len(glyphs_strict) == 1  # only the 30x30 blob passes
    assert len(glyphs_loose) == 2


def test_extract_glyphs_filters_large_blobs(tmp_path: Path) -> None:
    """Blobs exceeding max_area should be dropped."""
    img = _white_image(200, 100)
    _draw_black_rect(img, x=5, y=5, w=30, h=30)   # 900 px² — below ceiling
    _draw_black_rect(img, x=100, y=5, w=60, h=60)  # 3600 px² — above ceiling
    scan = tmp_path / "scan.png"
    _save_png(img, scan)

    glyphs = extract_glyphs(scan, max_area=1000)

    assert len(glyphs) == 1
    assert glyphs[0].x == 5


def test_extract_glyphs_default_max_area_drops_page_blobs(tmp_path: Path) -> None:
    """A blob covering >10 % of the page should be dropped by default."""
    img = _white_image(100, 100)  # 10 000 px total
    _draw_black_rect(img, x=0, y=0, w=100, h=100)  # fills entire page
    scan = tmp_path / "scan.png"
    _save_png(img, scan)

    # The single blob covers 100 % of the page, so it should be dropped.
    glyphs = extract_glyphs(scan)
    assert glyphs == []


def test_extract_glyphs_empty_image(tmp_path: Path) -> None:
    """An all-white image should yield no blobs."""
    img = _white_image(100, 100)
    scan = tmp_path / "scan.png"
    _save_png(img, scan)

    assert extract_glyphs(scan) == []


def test_extract_glyphs_raises_on_missing_image(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="could not load image"):
        extract_glyphs(tmp_path / "nonexistent.png")


def test_extract_glyphs_raises_on_bad_min_dimension(tmp_path: Path) -> None:
    img = _white_image(50, 50)
    scan = tmp_path / "scan.png"
    _save_png(img, scan)
    with pytest.raises(ExtractionError, match="min_dimension"):
        extract_glyphs(scan, min_dimension=0)


def test_extract_glyphs_sorting_is_hebrew_order(tmp_path: Path) -> None:
    """Hebrew reading order: top-to-bottom rows, right-to-left within rows."""
    img = _white_image(300, 200)
    # Row 1 (y=10): three blobs, right-to-left order expected
    _draw_black_rect(img, x=200, y=10, w=20, h=20)  # rightmost
    _draw_black_rect(img, x=100, y=10, w=20, h=20)  # middle
    _draw_black_rect(img, x=10,  y=10, w=20, h=20)  # leftmost
    # Row 2 (y=100): one blob
    _draw_black_rect(img, x=150, y=100, w=20, h=20)
    scan = tmp_path / "scan.png"
    _save_png(img, scan)

    glyphs = extract_glyphs(scan)

    assert len(glyphs) == 4
    # First three from row 1, right-to-left
    assert glyphs[0].x == 200
    assert glyphs[1].x == 100
    assert glyphs[2].x == 10
    # Last blob from row 2
    assert glyphs[3].y >= 100


# ---------------------------------------------------------------------------
# crop_glyph
# ---------------------------------------------------------------------------


def test_crop_glyph_returns_png_bytes(tmp_path: Path) -> None:
    img = _white_image(100, 100)
    _draw_black_rect(img, x=10, y=10, w=20, h=20)
    scan = tmp_path / "scan.png"
    _save_png(img, scan)

    glyph = Glyph(x=10, y=10, width=20, height=20)
    png_bytes = crop_glyph(scan, glyph)

    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 0
    # PNG magic bytes
    assert png_bytes[:4] == b"\x89PNG"


def test_crop_glyph_dimensions_match_bbox(tmp_path: Path) -> None:
    img = _white_image(100, 100)
    _draw_black_rect(img, x=5, y=5, w=25, h=35)
    scan = tmp_path / "scan.png"
    _save_png(img, scan)

    glyph = Glyph(x=5, y=5, width=25, height=35)
    png_bytes = crop_glyph(scan, glyph)

    # Decode the PNG and check dimensions
    buf = np.frombuffer(png_bytes, dtype=np.uint8)
    decoded = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    assert decoded is not None
    assert decoded.shape == (35, 25)  # (height, width)


def test_crop_glyph_is_binarised(tmp_path: Path) -> None:
    """The cropped image should contain only 0 and 255 pixel values."""
    img = _white_image(100, 100)
    # Draw a grey rectangle (not pure black) — after Otsu binarisation it becomes black
    img[20:40, 20:40] = 80
    scan = tmp_path / "scan.png"
    _save_png(img, scan)

    glyph = Glyph(x=20, y=20, width=20, height=20)
    png_bytes = crop_glyph(scan, glyph)

    buf = np.frombuffer(png_bytes, dtype=np.uint8)
    decoded = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    assert decoded is not None
    unique_vals = set(decoded.flatten().tolist())
    assert unique_vals <= {0, 255}


def test_crop_glyph_is_deterministic(tmp_path: Path) -> None:
    """Calling crop_glyph twice on the same input returns identical bytes."""
    img = _white_image(100, 100)
    _draw_black_rect(img, x=10, y=10, w=20, h=20)
    scan = tmp_path / "scan.png"
    _save_png(img, scan)

    glyph = Glyph(x=10, y=10, width=20, height=20)
    assert crop_glyph(scan, glyph) == crop_glyph(scan, glyph)


def test_crop_glyph_raises_on_missing_image(tmp_path: Path) -> None:
    glyph = Glyph(x=0, y=0, width=10, height=10)
    with pytest.raises(ExtractionError, match="could not load image"):
        crop_glyph(tmp_path / "nonexistent.png", glyph)


def test_crop_glyph_raises_on_out_of_bounds(tmp_path: Path) -> None:
    img = _white_image(50, 50)
    scan = tmp_path / "scan.png"
    _save_png(img, scan)

    out_of_bounds = Glyph(x=40, y=40, width=20, height=20)  # extends past 50x50
    with pytest.raises(ExtractionError, match="outside"):
        crop_glyph(scan, out_of_bounds)


# ---------------------------------------------------------------------------
# compute_ink_ratio
# ---------------------------------------------------------------------------


def _binarize_array(img: np.ndarray) -> np.ndarray:  # type: ignore[type-arg]
    """Binarise a synthetic BGR image the same way binarize_scan does."""
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    return binary


def test_ink_ratio_fully_filled() -> None:
    """A glyph bbox that is entirely ink should have ratio 1.0."""
    img = _white_image(50, 50)
    _draw_black_rect(img, x=0, y=0, w=50, h=50)  # entire image is black
    binary = _binarize_array(img)
    glyph = Glyph(x=0, y=0, width=50, height=50)
    ratio = compute_ink_ratio(binary, glyph)
    assert ratio == pytest.approx(1.0, abs=1e-6)


def test_ink_ratio_empty_crop() -> None:
    """A crop with no ink pixels should have ratio 0.0."""
    img = _white_image(50, 50)  # entirely white — no ink
    binary = _binarize_array(img)
    glyph = Glyph(x=0, y=0, width=50, height=50)
    ratio = compute_ink_ratio(binary, glyph)
    assert ratio == pytest.approx(0.0, abs=1e-6)


def test_ink_ratio_partial_fill() -> None:
    """Half-filled crop should yield ratio ≈ 0.5."""
    # 20x10 bbox: fill the top 10x10 half with black
    img = _white_image(40, 20)
    _draw_black_rect(img, x=0, y=0, w=10, h=10)
    binary = _binarize_array(img)
    glyph = Glyph(x=0, y=0, width=20, height=10)
    ratio = compute_ink_ratio(binary, glyph)
    # 10x10 ink in a 20x10 bbox → exactly 0.5
    assert ratio == pytest.approx(0.5, abs=1e-6)


def test_ink_ratio_is_in_unit_interval(tmp_path: Path) -> None:
    """ink_ratio must always be in [0.0, 1.0] for any binary input."""
    img = _white_image(100, 100)
    _draw_black_rect(img, x=10, y=10, w=30, h=30)
    scan = tmp_path / "scan.png"
    _save_png(img, scan)
    binary = binarize_scan(scan)
    glyph = Glyph(x=10, y=10, width=30, height=30)
    ratio = compute_ink_ratio(binary, glyph)
    assert 0.0 <= ratio <= 1.0


# ---------------------------------------------------------------------------
# compute_dhash / hamming_distance
# ---------------------------------------------------------------------------


def test_dhash_returns_integer() -> None:
    """compute_dhash must return a plain int."""
    img = _white_image(50, 50)
    _draw_black_rect(img, x=5, y=5, w=20, h=20)
    binary = _binarize_array(img)
    glyph = Glyph(x=5, y=5, width=20, height=20)
    h = compute_dhash(binary, glyph)
    assert isinstance(h, int)


def test_dhash_identical_glyphs_have_zero_distance() -> None:
    """The same crop hashed twice should produce identical hashes."""
    img = _white_image(60, 60)
    _draw_black_rect(img, x=10, y=10, w=30, h=30)
    binary = _binarize_array(img)
    glyph = Glyph(x=10, y=10, width=30, height=30)
    h1 = compute_dhash(binary, glyph)
    h2 = compute_dhash(binary, glyph)
    assert hamming_distance(h1, h2) == 0


def test_dhash_different_glyphs_have_positive_distance() -> None:
    """Two structurally different crops should produce hashes with distance > 0.

    Build the binary array directly (skip Otsu) so that glyph A has ink on
    its left half and glyph B has ink on its right half.  The resulting
    horizontal-difference patterns are mirror images → hashes differ.
    """
    binary = np.zeros((40, 100), dtype=np.uint8)
    # Glyph A: left 20 px of a 40x30 bbox are ink, right 20 px are background.
    binary[5:35, 0:20] = 255
    # Glyph B: right 20 px of a 40x30 bbox are ink, left 20 px are background.
    binary[5:35, 80:100] = 255
    g_a = Glyph(x=0, y=5, width=40, height=30)
    g_b = Glyph(x=60, y=5, width=40, height=30)
    ha = compute_dhash(binary, g_a)
    hb = compute_dhash(binary, g_b)
    assert hamming_distance(ha, hb) > 0


def test_hamming_distance_identical() -> None:
    assert hamming_distance(0b1010, 0b1010) == 0


def test_hamming_distance_all_differ() -> None:
    """0x00 vs 0xFF for an 8-bit value should give distance 8."""
    assert hamming_distance(0x00, 0xFF) == 8


def test_hamming_distance_single_bit() -> None:
    assert hamming_distance(0b0001, 0b0000) == 1


def test_dhash_default_is_64_bits() -> None:
    """Default hash_size=8 should produce a value expressible in ≤ 64 bits."""
    img = _white_image(50, 50)
    _draw_black_rect(img, x=5, y=5, w=20, h=20)
    binary = _binarize_array(img)
    glyph = Glyph(x=5, y=5, width=20, height=20)
    h = compute_dhash(binary, glyph)
    assert 0 <= h < (1 << 64)
