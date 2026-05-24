"""Generation profile: human-curated letter annotations for the generate pipeline.

A generation profile is a JSON config file that tells the generator
*exactly* which glyph bounding boxes to crop from which upstream scans,
and which Hebrew letter each glyph represents.  Because all bounding
boxes are explicitly declared by a human, the generator's output is
deterministic: same profile + same upstream revision → bit-identical
letter-set tree.

Typical workflow:

1. Run ``hletterscriptgen scan-blobs <scan>`` to discover CCA-detected
   blobs in a scan.
2. Review the blob list, assign Hebrew letter labels, and record the
   chosen bounding boxes in a ``generate_profile.json`` file.
3. Run ``hletterscriptgen generate --profile generate_profile.json
   --output ./out`` to produce letter_set.v1 documents.

Profile JSON shape::

    {
      "upstream_checkout": "../public-domain-hand-written-hebrew-scans",
      "writers": [
        {
          "writer_id": "writer_bialik",
          "attribution_method": "collection_metadata",
          "notes": "...",
          "scans": [
            {
              "entry_id": "commons__bialik_letter_safed_1927__p0001",
              "glyphs": [
                {"letter": "א", "x": 10, "y": 20, "width": 30, "height": 40},
                {"letter": "ב", "x": 55, "y": 22, "width": 28, "height": 38}
              ]
            }
          ]
        }
      ]
    }

The module exposes:

* :class:`GlyphAnnotation` — a single bbox + letter label.
* :class:`ScanAnnotation` — all annotated glyphs for one upstream scan.
* :class:`WriterAnnotation` — all annotated scans for one writer.
* :class:`GenerateProfile` — top-level config object (includes pre-computed
  ``config_hash`` for embedding in output documents).
* :class:`GenerateProfileError` — base error class.
* :func:`load_generate_profile` — read, validate, and return a
  :class:`GenerateProfile`; the profile's ``config_hash`` field is computed
  from the raw JSON at load time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hletterscriptgen import HEBREW_LETTERS
from hletterscriptgen.hashing import (
    config_hash as _compute_config_hash,
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GenerateProfileError(ValueError):
    """Raised when a generation profile file is invalid.

    ``path`` refers to the profile JSON file associated with the error.
    """

    def __init__(self, message: str, *, path: Path) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GlyphAnnotation:
    """A manually annotated glyph: one Hebrew letter at a specific bbox.

    ``letter`` must be a single character from the Hebrew block
    (U+05D0..U+05EA, base and final forms).  ``x``, ``y`` are the
    top-left corner of the bounding box in the scan's pixel space;
    ``width`` and ``height`` are its extent.  ``notes`` is optional.
    """

    letter: str      # single Hebrew character
    x: int           # left edge of bbox (px, ≥ 0)
    y: int           # top edge of bbox (px, ≥ 0)
    width: int       # bbox width (px, ≥ 1)
    height: int      # bbox height (px, ≥ 1)
    notes: str | None = None


@dataclass(frozen=True)
class ScanAnnotation:
    """All annotated glyphs for one upstream scan entry.

    ``entry_id`` identifies the upstream ``entries.jsonl`` record.
    ``glyphs`` must be non-empty.
    """

    entry_id: str
    glyphs: tuple[GlyphAnnotation, ...]


@dataclass(frozen=True)
class WriterAnnotation:
    """All annotated scans for one writer.

    ``writer_id`` is a stable, repo-unique identifier.
    ``attribution_method`` is the same vocabulary as
    :class:`hletterscriptgen.attribution.AttributionMethod`.
    ``scans`` must be non-empty.
    """

    writer_id: str
    attribution_method: str
    scans: tuple[ScanAnnotation, ...]
    notes: str | None = None


@dataclass(frozen=True)
class GenerateProfile:
    """Top-level generation profile config.

    ``upstream_checkout`` is the path to the local upstream repo checkout
    (used for both pinning the revision and resolving scan file paths).
    ``writers`` is a non-empty tuple of :class:`WriterAnnotation` records.
    ``config_hash`` is the SHA-256 hex digest of the canonical-JSON serialisation
    of the raw profile dict, computed at load time by :func:`load_generate_profile`.
    It is embedded in the ``generator.config_hash`` field of output documents so
    that the profile version that produced a dataset can be reconstructed.
    """

    upstream_checkout: Path
    writers: tuple[WriterAnnotation, ...]
    config_hash: str


# ---------------------------------------------------------------------------
# Internal parsing helpers
# ---------------------------------------------------------------------------


def _require_str(raw: dict[str, Any], key: str, context: str, *, path: Path) -> str:
    val = raw.get(key)
    if not isinstance(val, str):
        raise GenerateProfileError(
            f"{context}: '{key}' must be a non-null string, "
            f"got {type(val).__name__ if val is not None else 'null'}",
            path=path,
        )
    return val


def _require_int_ge(
    raw: dict[str, Any], key: str, minimum: int, context: str, *, path: Path
) -> int:
    val = raw.get(key)
    if not isinstance(val, int) or isinstance(val, bool):
        raise GenerateProfileError(
            f"{context}: '{key}' must be an integer, "
            f"got {type(val).__name__ if val is not None else 'null'}",
            path=path,
        )
    if val < minimum:
        raise GenerateProfileError(
            f"{context}: '{key}' must be ≥ {minimum}, got {val}",
            path=path,
        )
    return val


def _parse_glyph(raw: Any, index: int, scan_ctx: str, *, path: Path) -> GlyphAnnotation:
    ctx = f"{scan_ctx}/glyphs[{index}]"
    if not isinstance(raw, dict):
        raise GenerateProfileError(f"{ctx}: expected a JSON object", path=path)

    letter = _require_str(raw, "letter", ctx, path=path)
    if len(letter) != 1 or letter not in HEBREW_LETTERS:
        raise GenerateProfileError(
            f"{ctx}: 'letter' must be a single Hebrew character "
            f"(U+05D0..U+05EA), got {letter!r}",
            path=path,
        )

    x = _require_int_ge(raw, "x", 0, ctx, path=path)
    y = _require_int_ge(raw, "y", 0, ctx, path=path)
    width = _require_int_ge(raw, "width", 1, ctx, path=path)
    height = _require_int_ge(raw, "height", 1, ctx, path=path)

    notes = raw.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise GenerateProfileError(f"{ctx}: 'notes' must be a string if present", path=path)

    return GlyphAnnotation(letter=letter, x=x, y=y, width=width, height=height, notes=notes)


def _parse_scan(raw: Any, index: int, writer_ctx: str, *, path: Path) -> ScanAnnotation:
    ctx = f"{writer_ctx}/scans[{index}]"
    if not isinstance(raw, dict):
        raise GenerateProfileError(f"{ctx}: expected a JSON object", path=path)

    entry_id = _require_str(raw, "entry_id", ctx, path=path)
    if not entry_id.strip():
        raise GenerateProfileError(f"{ctx}: 'entry_id' must not be blank", path=path)

    raw_glyphs = raw.get("glyphs")
    if not isinstance(raw_glyphs, list) or not raw_glyphs:
        raise GenerateProfileError(
            f"{ctx}: 'glyphs' must be a non-empty list", path=path
        )

    glyphs = tuple(
        _parse_glyph(g, i, f"{ctx}", path=path) for i, g in enumerate(raw_glyphs)
    )
    return ScanAnnotation(entry_id=entry_id, glyphs=glyphs)


def _parse_writer(raw: Any, index: int, *, path: Path) -> WriterAnnotation:
    ctx = f"writers[{index}]"
    if not isinstance(raw, dict):
        raise GenerateProfileError(f"{ctx}: expected a JSON object", path=path)

    writer_id = _require_str(raw, "writer_id", ctx, path=path)
    if not writer_id.strip():
        raise GenerateProfileError(f"{ctx}: 'writer_id' must not be blank", path=path)

    attribution_method = _require_str(raw, "attribution_method", ctx, path=path)
    if not attribution_method.strip():
        raise GenerateProfileError(
            f"{ctx}: 'attribution_method' must not be blank", path=path
        )

    raw_scans = raw.get("scans")
    if not isinstance(raw_scans, list) or not raw_scans:
        raise GenerateProfileError(
            f"{ctx}: 'scans' must be a non-empty list", path=path
        )

    scans = tuple(
        _parse_scan(s, i, f"{ctx}", path=path) for i, s in enumerate(raw_scans)
    )

    notes = raw.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise GenerateProfileError(
            f"{ctx}: 'notes' must be a string if present", path=path
        )

    return WriterAnnotation(
        writer_id=writer_id,
        attribution_method=attribution_method,
        scans=scans,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_generate_profile(path: Path) -> GenerateProfile:
    """Read and validate a generation profile JSON file.

    Returns a :class:`GenerateProfile` whose ``config_hash`` field contains
    the SHA-256 hex digest of the canonical-JSON serialisation of the raw
    profile dict.  That hash is embedded in the ``generator.config_hash``
    field of output ``letter_set.v1`` documents so that the profile version
    that produced a dataset can be reconstructed.

    Raises :class:`GenerateProfileError` when the file is missing, not
    valid JSON, or structurally invalid.  Raises :class:`OSError` for
    other I/O failures.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise GenerateProfileError(
            f"generation profile file not found: {path}", path=path
        ) from exc

    try:
        raw: dict[str, Any] = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise GenerateProfileError(f"invalid JSON: {exc.msg}", path=path) from exc

    if not isinstance(raw, dict):
        raise GenerateProfileError("expected a JSON object at top level", path=path)

    raw_checkout = raw.get("upstream_checkout")
    if not isinstance(raw_checkout, str) or not raw_checkout.strip():
        raise GenerateProfileError(
            "'upstream_checkout' must be a non-empty string", path=path
        )

    raw_writers = raw.get("writers")
    if not isinstance(raw_writers, list) or not raw_writers:
        raise GenerateProfileError("'writers' must be a non-empty list", path=path)

    writers = tuple(_parse_writer(w, i, path=path) for i, w in enumerate(raw_writers))

    # Enforce uniqueness of writer_ids and entry_ids across all writers.
    seen_writer_ids: set[str] = set()
    seen_entry_ids: dict[str, str] = {}  # entry_id → writer_id
    for wa in writers:
        if wa.writer_id in seen_writer_ids:
            raise GenerateProfileError(
                f"duplicate writer_id {wa.writer_id!r}", path=path
            )
        seen_writer_ids.add(wa.writer_id)
        for sa in wa.scans:
            if sa.entry_id in seen_entry_ids:
                raise GenerateProfileError(
                    f"entry_id {sa.entry_id!r} appears under both "
                    f"{seen_entry_ids[sa.entry_id]!r} and {wa.writer_id!r}",
                    path=path,
                )
            seen_entry_ids[sa.entry_id] = wa.writer_id

    # Resolve upstream_checkout relative to the profile file's parent dir.
    checkout_path = (path.parent / raw_checkout).resolve()

    return GenerateProfile(
        upstream_checkout=checkout_path,
        writers=writers,
        config_hash=_compute_config_hash(raw),
    )


__all__ = [
    "GenerateProfile",
    "GenerateProfileError",
    "GlyphAnnotation",
    "ScanAnnotation",
    "WriterAnnotation",
    "load_generate_profile",
]
