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
* :class:`Glyph` — frozen dataclass for a detected blob's bounding box.
* :func:`extract_glyphs` — detect blobs in a scan via CCA.
* :func:`crop_glyph` — crop one blob from the binarised scan, return PNG bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Minimum bounding-box width AND height in pixels, per issue #16 decision D2.
MIN_GLYPH_PX: int = 16

# Upper-area ceiling as a fraction of total image area.  Blobs that cover
# more than this fraction of the page are assumed to be noise (stamps,
# ruled lines, bleed-through from the verso).  Empirical calibration of
# this value is deferred to a later sub-PR; 10 % is a conservative default.
_DEFAULT_MAX_AREA_FRACTION: float = 0.10


class ExtractionError(Exception):
    """Raised when glyph extraction fails.

    Covers both missing-library errors (opencv not installed) and
    runtime errors (image not found, encode failure, out-of-bounds crop).
    """


@dataclass(frozen=True)
class Glyph:
    """Bounding box of a connected component detected in a scan image.

    Coordinates are in the scan image's pixel space.  ``x`` and ``y`` are
    the top-left corner of the bounding box; ``width`` and ``height`` are
    its extent.  All values are non-negative integers; ``width`` and
    ``height`` are ≥ 1.

    Glyphs returned by :func:`extract_glyphs` are sorted by
    ``(y, -x)`` — top-to-bottom rows, right-to-left within each row —
    consistent with Hebrew reading order.
    """

    x: int
    y: int
    width: int
    height: int


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
    5. Drop blobs where ``width < min_dimension`` or ``height < min_dimension``
       (quality floor, issue #16 D2).
    6. Drop blobs whose pixel area exceeds ``max_area`` (noise ceiling;
       defaults to 10 % of total image area when ``None``).
    7. Sort survivors by ``(y, -x)`` — top row first, right-to-left within
       a row — and return them as :class:`Glyph` records.

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

    try:
        import cv2
    except ImportError as exc:
        raise ExtractionError(
            "opencv-python-headless is required for glyph extraction; "
            "install it with: pip install hletterscriptgen[cv]"
        ) from exc

    img = cv2.imread(str(image_path))
    if img is None:
        raise ExtractionError(f"could not load image: {image_path}")

    img_h, img_w = img.shape[:2]
    effective_max_area = (
        max_area if max_area is not None else int(img_h * img_w * _DEFAULT_MAX_AREA_FRACTION)
    )

    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

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

    # Sort: top-to-bottom by y, then right-to-left by x within each row.
    glyphs.sort(key=lambda g: (g.y, -g.x))
    return glyphs


def crop_glyph(image_path: Path, glyph: Glyph) -> bytes:
    """Crop a glyph region from the binarised scan and return PNG bytes.

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
    try:
        import cv2
    except ImportError as exc:
        raise ExtractionError(
            "opencv-python-headless is required for glyph extraction; "
            "install it with: pip install hletterscriptgen[cv]"
        ) from exc

    img = cv2.imread(str(image_path))
    if img is None:
        raise ExtractionError(f"could not load image: {image_path}")

    img_h, img_w = img.shape[:2]
    x, y, w, h = glyph.x, glyph.y, glyph.width, glyph.height

    if x < 0 or y < 0 or x + w > img_w or y + h > img_h:
        raise ExtractionError(
            f"glyph bbox (x={x}, y={y}, w={w}, h={h}) falls outside "
            f"image dimensions {img_w}×{img_h}: {image_path}"
        )

    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    crop = binary[y : y + h, x : x + w]

    ok, buf = cv2.imencode(".png", crop)
    if not ok:
        raise ExtractionError(f"failed to encode glyph crop as PNG: {image_path}")

    return bytes(buf.tobytes())


__all__ = [
    "MIN_GLYPH_PX",
    "ExtractionError",
    "Glyph",
    "crop_glyph",
    "extract_glyphs",
]
