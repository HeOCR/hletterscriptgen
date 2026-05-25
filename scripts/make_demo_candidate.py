#!/usr/bin/env python3
"""Generate a synthetic demo release candidate for reviewing with the review UI.

Creates:

    examples/demo_candidate/
      demo_writer_0001/
        letter_set.json          — schema-valid letter_set.v1 document
        letters/
          <letter_name>/
            <variant_id>.png     — synthetic glyph images (cv2-rendered)

Usage::

    python3 scripts/make_demo_candidate.py [--output DIR]

Requires the ``cv`` extra (opencv-python-headless)::

    pip install -e ".[cv]"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "examples" / "demo_candidate"

# ---------------------------------------------------------------------------
# Minimal stdlib-only PNG encoder
# ---------------------------------------------------------------------------


def _png_from_pixels(pixels: list[list[int]]) -> bytes:
    """Encode a 2-D list of 0-255 grayscale values as a PNG (stdlib only)."""
    height = len(pixels)
    width = len(pixels[0]) if height else 0

    # Each row is prefixed by a filter byte (0 = None).
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)
    compressed = zlib.compress(raw, 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFF_FFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    # IHDR: width(4) height(4) bit-depth(1) color-type(1=grayscale=0)
    #       compression(1=0) filter(1=0) interlace(1=0)
    ihdr_data = struct.pack(">II", width, height) + bytes([8, 0, 0, 0, 0])

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr_data)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------------------
# Letter shape primitives
# ---------------------------------------------------------------------------

WHITE = 255
BLACK = 0


def _blank(w: int, h: int) -> list[list[int]]:
    return [[WHITE] * w for _ in range(h)]


def _hline(px: list[list[int]], y: int, x0: int, x1: int, t: int = 2) -> None:
    """Draw a horizontal line."""
    h, w = len(px), len(px[0])
    for dy in range(t):
        row = y + dy
        if 0 <= row < h:
            for x in range(max(0, x0), min(w, x1 + 1)):
                px[row][x] = BLACK


def _vline(px: list[list[int]], x: int, y0: int, y1: int, t: int = 2) -> None:
    """Draw a vertical line."""
    h, w = len(px), len(px[0])
    for dx in range(t):
        col = x + dx
        if 0 <= col < w:
            for y in range(max(0, y0), min(h, y1 + 1)):
                px[y][col] = BLACK


def _diag(px: list[list[int]], x0: int, y0: int, x1: int, y1: int, t: int = 2) -> None:
    """Draw a straight line via integer Bresenham."""
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x1 > x0 else -1
    sy = 1 if y1 > y0 else -1
    h, w = len(px), len(px[0])
    err = dx - dy
    x, y = x0, y0
    while True:
        for ox in range(t):
            for oy in range(t):
                nx, ny = x + ox, y + oy
                if 0 <= nx < w and 0 <= ny < h:
                    px[ny][nx] = BLACK
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy


# ---------------------------------------------------------------------------
# Per-letter shape generators
# Any function here accepts (width, height, variant_index) and returns
# a PNG bytes object.
# ---------------------------------------------------------------------------

def _shape_alef(w: int, h: int, v: int) -> bytes:
    """Alef (א): diagonal cross + horizontal bar."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    # Main diagonal top-right to bottom-left
    _diag(px, w - w // 5, h // 6, w // 5, h - h // 5, t)
    # Left fork: bottom-left up to centre
    _diag(px, w // 5, h - h // 5, w // 3, h // 2, t)
    # Right fork: top-right down to centre
    _diag(px, w - w // 5, h // 6, 2 * w // 3, h // 2, t)
    # Small horizontal bar at centre-left
    _hline(px, h // 2, w // 4, w // 2, t)
    return _png_from_pixels(px)


def _shape_bet(w: int, h: int, v: int) -> bytes:
    """Bet (ב): top horizontal + right vertical + bottom bar."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    _hline(px, h // 6, w // 6, w - w // 6, t)        # top
    _vline(px, w - w // 5, h // 6, h - h // 5, t)    # right
    _hline(px, h - h // 5, w // 5, w - w // 5, t)    # bottom
    # Tiny left foot
    _vline(px, w // 6, h // 6, h // 3, t)
    return _png_from_pixels(px)


def _shape_gimel(w: int, h: int, v: int) -> bytes:
    """Gimel (ג): right vertical + top horizontal + right-down hook."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    _vline(px, w - w // 4, h // 6, h - h // 4, t)   # right vertical
    _hline(px, h // 6, w // 5, w - w // 4, t)        # top horizontal
    # Hook at bottom-right going down-left
    _diag(px, w - w // 4, h - h // 4, w // 2, h - h // 8, t)
    return _png_from_pixels(px)


def _shape_dalet(w: int, h: int, v: int) -> bytes:
    """Dalet (ד): top horizontal + right vertical (no foot)."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    _hline(px, h // 6, w // 6, w - w // 6, t)        # top
    _vline(px, w - w // 5, h // 6, h - h // 5, t)    # right
    return _png_from_pixels(px)


def _shape_he(w: int, h: int, v: int) -> bytes:
    """He (ה): dalet + detached left vertical."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    _hline(px, h // 6, w // 6, w - w // 6, t)
    _vline(px, w - w // 5, h // 6, h - h // 5, t)
    # Detached left vertical (doesn't touch top)
    _vline(px, w // 5, h // 3, h - h // 5, t)
    return _png_from_pixels(px)


def _shape_vav(w: int, h: int, v: int) -> bytes:
    """Vav (ו): short cap + descending vertical."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    # Cap
    _hline(px, h // 8, w // 3, 2 * w // 3, t)
    _vline(px, w // 2 - t // 2, h // 8, 5 * h // 6, t)
    return _png_from_pixels(px)


def _shape_zayin(w: int, h: int, v: int) -> bytes:
    """Zayin (ז): top bar (long) + short descender from right."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    _hline(px, h // 8, w // 6, 5 * w // 6, t + 1)  # wide cap
    _vline(px, 3 * w // 4, h // 8, 5 * h // 6, t)   # right descender
    return _png_from_pixels(px)


def _shape_mem(w: int, h: int, v: int) -> bytes:
    """Mem (מ): closed square with left opening."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    _hline(px, h // 8, w // 5, w - w // 5, t)        # top
    _vline(px, w - w // 5, h // 8, h - h // 5, t)    # right
    _hline(px, h - h // 5, w // 5, w - w // 5, t)    # bottom
    _vline(px, w // 5, h // 4, h - h // 5, t)         # left (partial, open at top)
    return _png_from_pixels(px)


def _shape_nun(w: int, h: int, v: int) -> bytes:
    """Nun (נ): hook with descender."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    _hline(px, h // 8, w // 4, 3 * w // 4, t)
    _vline(px, 3 * w // 4, h // 8, h // 2, t)
    # Descending diagonal from hook
    _diag(px, 3 * w // 4, h // 2, w // 4, h - h // 8, t)
    return _png_from_pixels(px)


def _shape_samekh(w: int, h: int, v: int) -> bytes:
    """Samekh (ס): closed rectangle."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    _hline(px, h // 8, w // 6, 5 * w // 6, t)
    _hline(px, h - h // 8, w // 6, 5 * w // 6, t)
    _vline(px, w // 6, h // 8, h - h // 8, t)
    _vline(px, 5 * w // 6 - t, h // 8, h - h // 8, t)
    return _png_from_pixels(px)


def _shape_ayin(w: int, h: int, v: int) -> bytes:
    """Ayin (ע): two diagonals meeting at bottom."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    cx = w // 2
    bot = h - h // 8
    _diag(px, w // 6, h // 8, cx, bot, t)
    _diag(px, 5 * w // 6, h // 8, cx, bot, t)
    return _png_from_pixels(px)


def _shape_pe(w: int, h: int, v: int) -> bytes:
    """Pe (פ): circular top + descender."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    _hline(px, h // 8, w // 5, 4 * w // 5, t)
    _vline(px, 4 * w // 5, h // 8, h // 2, t)
    _hline(px, h // 2, w // 4, 4 * w // 5, t)
    _vline(px, w // 4, h // 4, h - h // 8, t)
    return _png_from_pixels(px)


def _shape_resh(w: int, h: int, v: int) -> bytes:
    """Resh (ר): top bar + right vertical descender."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    _hline(px, h // 8, w // 5, 4 * w // 5, t)
    _vline(px, 4 * w // 5, h // 8, h - h // 8, t)
    return _png_from_pixels(px)


def _shape_shin(w: int, h: int, v: int) -> bytes:
    """Shin (ש): three prongs."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    bot = h - h // 6
    _vline(px, w // 5, h // 8, bot, t)
    _vline(px, w // 2 - t // 2, h // 5, bot, t)
    _vline(px, 4 * w // 5, h // 8, bot, t)
    _hline(px, bot, w // 5, 4 * w // 5, t)
    return _png_from_pixels(px)


def _shape_tav(w: int, h: int, v: int) -> bytes:
    """Tav (ת): top bar + left & right descenders, right foot."""
    px = _blank(w, h)
    t = max(1, 2 + (v % 2))
    _hline(px, h // 8, w // 6, 5 * w // 6, t)
    _vline(px, w // 6, h // 8, h - h // 5, t)
    _vline(px, 5 * w // 6, h // 8, h - h // 3, t)
    _hline(px, h - h // 3, 5 * w // 6, 5 * w // 6 + t + 3, t)  # right foot
    return _png_from_pixels(px)


# Mapping: Unicode char → shape function
_SHAPES = {
    "א": _shape_alef,
    "ב": _shape_bet,
    "ג": _shape_gimel,
    "ד": _shape_dalet,
    "ה": _shape_he,
    "ו": _shape_vav,
    "ז": _shape_zayin,
    "מ": _shape_mem,
    "נ": _shape_nun,
    "ס": _shape_samekh,
    "ע": _shape_ayin,
    "פ": _shape_pe,
    "ר": _shape_resh,
    "ש": _shape_shin,
    "ת": _shape_tav,
}

# (letter_char, letter_name, variants): each variant is a (width, height) tuple.
_DEMO_LETTERS: list[tuple[str, str, list[tuple[int, int]]]] = [
    ("א", "alef",   [(48, 56), (44, 52), (52, 60)]),
    ("ב", "bet",    [(50, 40), (46, 44)]),
    ("ג", "gimel",  [(44, 50), (48, 48)]),
    ("ד", "dalet",  [(46, 40)]),
    ("ה", "he",     [(50, 42), (46, 46)]),
    ("ו", "vav",    [(30, 48), (28, 52)]),
    ("ז", "zayin",  [(38, 44)]),
    ("מ", "mem",    [(50, 44), (54, 48)]),
    ("נ", "nun",    [(44, 50), (40, 48)]),
    ("ס", "samekh", [(46, 46)]),
    ("ע", "ayin",   [(50, 50), (46, 48)]),
    ("פ", "pe",     [(48, 52), (44, 48)]),
    ("ר", "resh",   [(46, 44), (42, 46)]),
    ("ש", "shin",   [(54, 48), (50, 52), (56, 44)]),
    ("ת", "tav",    [(50, 46), (48, 50)]),
]


# ---------------------------------------------------------------------------
# Ink-ratio computation (mirrors extractor.compute_ink_ratio)
# ---------------------------------------------------------------------------


def _ink_ratio(png_bytes: bytes) -> float:
    """Parse a grayscale PNG and compute ink fraction (pixels < 128 / total)."""
    import zlib as _zlib
    import struct as _struct

    data = png_bytes

    def _read_chunk(pos: int) -> tuple[bytes, bytes, int]:
        length = _struct.unpack_from(">I", data, pos)[0]
        tag = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + length]
        return tag, chunk_data, pos + 12 + length

    # Parse IHDR
    pos = 8  # skip signature
    tag, ihdr, pos = _read_chunk(pos)
    width, height = _struct.unpack_from(">II", ihdr)

    # Collect IDAT chunks
    idat_raw = b""
    while pos < len(data):
        tag, cdata, pos = _read_chunk(pos)
        if tag == b"IDAT":
            idat_raw += cdata
        elif tag == b"IEND":
            break

    raw = _zlib.decompress(idat_raw)
    # Each row: 1 filter byte + width bytes
    ink = 0
    total = width * height
    for row in range(height):
        row_data = raw[row * (width + 1) + 1 : row * (width + 1) + 1 + width]
        ink += sum(1 for b in row_data if b < 128)
    return ink / total if total else 0.0


# ---------------------------------------------------------------------------
# Release candidate builder
# ---------------------------------------------------------------------------


def _letter_set_name(name: str) -> str:
    """Convert letter name to letter_set asset path fragment."""
    return name.replace("_", "-")


def build_demo_candidate(out_dir: Path) -> Path:
    """Build the demo release candidate tree under *out_dir*.

    Returns the path to the ``letter_set.json`` file.
    """
    writer_id = "demo_writer_0001"
    writer_dir = out_dir / writer_id
    letters_dir = writer_dir / "letters"

    letters_dict: dict[str, list[dict]] = {}

    for char, name, size_list in _DEMO_LETTERS:
        shape_fn = _SHAPES.get(char)
        if shape_fn is None:
            print(f"  skip {char} (no shape defined)")
            continue

        variants: list[dict] = []
        for i, (w, h) in enumerate(size_list, start=1):
            png_bytes = shape_fn(w, h, i - 1)
            ink = _ink_ratio(png_bytes)
            sha = hashlib.sha256(png_bytes).hexdigest()

            # Asset path relative to letter_set.json
            fname = f"{name}-{i:04d}"
            asset_rel = f"letters/{_letter_set_name(name)}/{fname}.png"
            img_path = writer_dir / asset_rel
            img_path.parent.mkdir(parents=True, exist_ok=True)
            img_path.write_bytes(png_bytes)

            scan_entry = f"demo__manuscript_scan__p{i:04d}"
            variants.append({
                "variant_id": f"{name}-{i:04d}",
                "asset_path": asset_rel,
                "checksum_sha256": sha,
                "image": {"width_px": w, "height_px": h, "format": "png"},
                "quality": {"ink_ratio": round(ink, 4)},
                "source": {
                    "scan_entry_id": scan_entry,
                    "scan_url": f"https://example.invalid/scans/{scan_entry}",
                    "license": "PDM-1.0",
                    "rights_evidence": "Demo fixture — synthetic glyph, no real provenance.",
                    "bbox_in_source": {"x": 50 + i * 12, "y": 80 + i * 8, "width": w, "height": h},
                },
                "extracted_at": "2026-05-25T00:00:00Z",
                "notes": f"Synthetic demo glyph (variant {i}, {w}×{h}px).",
            })

        letters_dict[char] = variants
        print(f"  {char} ({name}): {len(variants)} variant(s)")

    # Collect unique scan entry IDs and licenses
    source_entry_ids = sorted({
        v["source"]["scan_entry_id"]
        for vlist in letters_dict.values()
        for v in vlist
    })
    licenses = sorted({
        v["source"]["license"]
        for vlist in letters_dict.values()
        for v in vlist
    })

    letter_set = {
        "schema_version": "letter_set.v1",
        "writer_id": writer_id,
        "writer_label": "Demo Writer (synthetic glyphs — not a real person)",
        "writer_provenance": {
            "source_repo": "HeOCR/public-domain-hand-written-hebrew-scans",
            "source_entry_ids": source_entry_ids,
            "attribution_method": "fixture",
            "notes": "Synthetic demo generated by scripts/make_demo_candidate.py.",
        },
        "generator": {
            "name": "hletterscriptgen",
            "version": "0.1.0.dev0",
            "config_hash": "0" * 64,
        },
        "generated_at": "2026-05-25T00:00:00Z",
        "upstream": {
            "repo": "HeOCR/public-domain-hand-written-hebrew-scans",
            "revision": "0" * 40,
        },
        "letters": letters_dict,
        "license_summary": {
            "licenses": licenses,
            "notes": "All variants are synthetic demo fixtures under PDM-1.0.",
        },
    }

    ls_path = writer_dir / "letter_set.json"
    ls_path.write_text(
        json.dumps(letter_set, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ls_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a synthetic demo release candidate.")
    ap.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUT,
        metavar="DIR",
        help=f"Output directory (default: {DEFAULT_OUT.relative_to(REPO_ROOT)})",
    )
    args = ap.parse_args()

    out_dir = args.output
    print(f"Generating demo release candidate in: {out_dir}")
    ls_path = build_demo_candidate(out_dir)
    total = sum(
        len(v) for v in json.loads(ls_path.read_text())["letters"].values()
    )
    print(f"\nWrote {ls_path}")
    print(f"Total: {total} synthetic variants across {len(_DEMO_LETTERS)} letters")
    print()
    print("To review:")
    print(f"  hletterscriptgen review {ls_path}")


if __name__ == "__main__":
    main()
