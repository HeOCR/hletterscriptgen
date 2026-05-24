"""CCA-based glyph extraction from handwritten Hebrew page scans.

Implements the Option A segmentation approach chosen in M3 sub-PR 1:
connected-component analysis (CCA) via ``opencv-python-headless`` with
Otsu binarisation.  See ``docs/design/segmentation-approach.md`` for
the decision record, algorithm spec, and known failure modes.

``opencv-python-headless`` is an *optional* dependency (install with
``pip install hletterscriptgen[cv]``).  All public functions raise
:class:`ExtractionError` when the library is not available, rather than
an import-time ``ImportError``, so the rest of the package stays
importable on environments without the CV stack.

The module exposes:

* :data:`MIN_GLYPH_PX` — minimum bounding-box dimension (px).
* :data:`DEFAULT_MAX_AREA_FRACTION` — default upper-area ceiling as a fraction of page area.
* :class:`Glyph` — frozen dataclass for a detected blob's bounding box.
* :func:`binarize_scan` — load a scan and return its Otsu-binarised array.
* :func:`crop_binary` — crop a glyph from an already-binarised array.
* :func:`extract_glyphs` — detect blobs in a scan via CCA.
* :func:`crop_glyph` — convenience wrapper: binarize a scan and crop one blob.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Minimum bounding-box width AND height in pixels, per issue #16 decision D2.
MIN_GLYPH_PX: int = 16

# Upper-area ceiling as a fraction of total image area.  Blobs that cover
# more than this fraction of the page are assumed to be noise (stamps,
# ruled lines, bleed-through from the verso).  Empirical calibration of
# this value is deferred to a later sub-PR; 10 % is a conservative default.
DEFAULT_MAX_AREA_FRACTION: float = 0.10


class ExtractionError(Exception):
    """Raised when glyph extraction fails.

    Covers both missing-library errors (opencv not installed) and
    runtime errors (image not found, encode failure, out-of-bounds crop).
    """


def _require_cv2() -> Any:
    """Return the ``cv2`` module, raising :class:`ExtractionError` if not installed."""
    try:
        import cv2

        return cv2
    except ImportError as exc:
        raise ExtractionError(
            "opencv-python-headless is required for glyph extraction; "
            "install it with: pip install hletterscriptgen[cv]"
        ) from exc


@dataclass(frozen=True)
class Glyph:
    """Bounding box of a connected component detected in a scan image.

    Coordinates are in the scan image's pixel space.  ``x`` and ``y`` are
    the top-left corner of the bounding box; ``width`` and ``height`` are
    its extent.  All values are non-negative integers; ``width`` and
    ``height`` are ≥ 1.

    Glyphs returned by :func:`extract_glyphs` are sorted by ascending ``y``
    first, then descending ``x`` within each row.
    """

    x: int
    y: int
    width: int
    height: int


def binarize_scan(image_path: Path) -> Any:
    """Load a scan image and return a binarised (Otsu) single-channel array.

    Applies ``THRESH_BINARY_INV | THRESH_OTSU`` so that ink pixels become
    foreground (255) and background pixels become 0.  The result is a
    2-D uint8 NumPy array with the same spatial dimensions as the source image.

    Calling this once and passing the result to :func:`crop_binary` for each
    glyph is more efficient than calling :func:`crop_glyph` per glyph, because
    it avoids redundant image I/O and re-binarisation.

    Parameters
    ----------
    image_path:
        Path to the scan image (JPEG, PNG, TIFF, or any format OpenCV can decode).

    Raises
    ------
    ExtractionError
        When ``opencv-python-headless`` is not installed or the image cannot
        be read.
    """
    cv2 = _require_cv2()
    img = cv2.imread(str(image_path))
    if img is None:
        raise ExtractionError(f"could not load image: {image_path}")
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    return binary


def crop_binary(binary: Any, glyph: Glyph) -> bytes:
    """Crop a glyph region from a binarised array and return PNG bytes.

    Unlike :func:`crop_glyph`, this function operates on an already-binarised
    array (the result of :func:`binarize_scan`), avoiding a redundant image
    load and Otsu threshold per glyph.  Prefer this when cropping multiple
    glyphs from the same scan.

    Parameters
    ----------
    binary:
        A 2-D uint8 NumPy array produced by :func:`binarize_scan` (or
        equivalent Otsu binarisation).  Shape is ``(height, width)``.
    glyph:
        Bounding box to crop, in the image's pixel space.

    Returns
    -------
    bytes
        PNG-encoded bytes of the cropped region.

    Raises
    ------
    ExtractionError
        When OpenCV is not installed, the glyph bbox falls outside the array
        dimensions, or PNG encoding fails.
    """
    cv2 = _require_cv2()
    img_h, img_w = binary.shape[:2]
    x, y, w, h = glyph.x, glyph.y, glyph.width, glyph.height

    if x < 0 or y < 0 or x + w > img_w or y + h > img_h:
        raise ExtractionError(
            f"glyph bbox (x={x}, y={y}, w={w}, h={h}) falls outside "
            f"image dimensions {img_w}x{img_h}"
        )

    crop = binary[y : y + h, x : x + w]
    ok, buf = cv2.imencode(".png", crop)
    if not ok:
        raise ExtractionError("failed to encode glyph crop as PNG")
    return bytes(buf.tobytes())


def extract_glyphs(
    image_path: Path,
    *,
    min_dimension: int = MIN_GLYPH_PX,
    max_area: int | None = None,
) -> list[Glyph]:
    """Detect letter glyphs in a scan via connected-component analysis.

    Algorithm (per ``docs/design/segmentation-approach.md``):

    1. Load the scan image (BGR).
    2. Convert to greyscale.
    3. Binarise with Otsu's method (``THRESH_BINARY_INV`` — ink pixels
       become foreground / 255, background becomes 0).
    4. Run ``connectedComponentsWithStats`` to label foreground blobs.
       8-connectivity is used so that diagonal contacts (common in cursive
       Hebrew script) are treated as part of the same component; 4-connectivity
       would incorrectly split glyphs at diagonal junctions.
    5. Drop blobs where ``width < min_dimension`` or ``height < min_dimension``
       (quality floor, issue #16 D2).
    6. Drop blobs whose pixel area exceeds ``max_area`` (noise ceiling;
       defaults to 10 % of total image area when ``None``).
    7. Sort survivors by ascending ``y`` first, then descending ``x`` within
       each row, and return them as :class:`Glyph` records.

    .. note::
        Deskew pre-processing is intentionally omitted from M3 — the
        failure-mode analysis rates skew as low-severity for the current
        corpus.  Add a Hough-line deskew step before binarisation if
        empirical scan quality demands it.

    .. note::
        Nikud (diacritical marks) are emitted as separate blobs when they
        exceed ``min_dimension``.  Merging them with their parent letter
        body is out of scope for M3; deferred to M4.

    Parameters
    ----------
    image_path:
        Path to the scan image (JPEG, PNG, TIFF, or any format OpenCV can
        decode).
    min_dimension:
        Minimum bounding-box width *and* height in pixels.  A blob must
        satisfy both constraints to survive.  Defaults to :data:`MIN_GLYPH_PX`.
    max_area:
        Maximum bounding-box area in pixels.  Blobs with a pixel area
        strictly greater than this are dropped as likely noise.  When
        ``None`` (default), the ceiling is set to 10 % of the image's
        total area at runtime.

    Raises
    ------
    ExtractionError
        When ``opencv-python-headless`` is not installed, the image cannot
        be read, or ``min_dimension`` < 1.
    """
    if min_dimension < 1:
        raise ExtractionError(f"min_dimension must be ≥ 1, got {min_dimension}")

    cv2 = _require_cv2()

    img = cv2.imread(str(image_path))
    if img is None:
        raise ExtractionError(f"could not load image: {image_path}")

    img_h, img_w = img.shape[:2]
    effective_max_area = (
        max_area if max_area is not None else int(img_h * img_w * DEFAULT_MAX_AREA_FRACTION)
    )

    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

    # 8-connectivity: diagonal contacts (common in Hebrew cursive) belong to the
    # same component; 4-connectivity would incorrectly split them.
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

    glyphs: list[Glyph] = []
    # Label 0 is the background component — start at 1.
    for i in range(1, num_labels):
        x = int(stats[i, cv2.CC_STAT_LEFT])
        y = int(stats[i, cv2.CC_STAT_TOP])
        w = int(stats[i, cv2.CC_STAT_WIDTH])
        h = int(stats[i, cv2.CC_STAT_HEIGHT])
        area = int(stats[i, cv2.CC_STAT_AREA])

        if w < min_dimension or h < min_dimension:
            continue
        if area > effective_max_area:
            continue

        glyphs.append(Glyph(x=x, y=y, width=w, height=h))

    # Sort: ascending y (top-to-bottom rows), then descending x within each row.
    glyphs.sort(key=lambda g: (g.y, -g.x))
    return glyphs


def crop_glyph(image_path: Path, glyph: Glyph) -> bytes:
    """Crop a glyph region from a scan image and return PNG bytes.

    Convenience wrapper around :func:`binarize_scan` and :func:`crop_binary`.
    When cropping multiple glyphs from the same scan, prefer calling
    :func:`binarize_scan` once and :func:`crop_binary` for each glyph to
    avoid re-loading and re-binarising the image on every call.

    The crop is taken from the *binarised* (Otsu) image, not the original
    colour scan, so the returned PNG contains only black ink (255) and
    white background (0) pixels.

    Parameters
    ----------
    image_path:
        Path to the source scan image.
    glyph:
        Bounding box to crop, in the scan's pixel space.

    Returns
    -------
    bytes
        PNG-encoded bytes of the cropped region.

    Raises
    ------
    ExtractionError
        When the library is not installed, the image cannot be read, the
        glyph bbox falls outside the image boundaries, or PNG encoding
        fails.
    """
    return crop_binary(binarize_scan(image_path), glyph)


__all__ = [
    "DEFAULT_MAX_AREA_FRACTION",
    "MIN_GLYPH_PX",
    "ExtractionError",
    "Glyph",
    "binarize_scan",
    "crop_binary",
    "crop_glyph",
    "extract_glyphs",
]
