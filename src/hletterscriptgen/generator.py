"""End-to-end glyph extraction pipeline (M3 MVP).

Orchestrates the full generate flow:

1. Pin the upstream checkout revision.
2. Load and index all eligible upstream entries.
3. For each writer → each scan → each annotated glyph:
   a. Look up the upstream entry; skip ineligible entries (warn).
   b. Resolve the scan file path from the upstream checkout.
   c. Crop the glyph from the binarised scan.
   d. Write the PNG to the output tree.
   e. Record a ``variant`` for the letter_set.v1 document.
4. Build and validate the ``letter_set.v1`` document for each writer.
5. Write ``letter_set.json`` to the writer's output directory.

Output tree structure::

    <output_dir>/
      <writer_id>/
        letter_set.json
        glyphs/
          <entry_id>__<letter>__<x>_<y>_<w>_<h>.png

All paths in ``letter_set.json`` are POSIX-relative to the writer's
output directory.  The ``variant_id`` is derived deterministically from
the entry_id, letter, and bounding box.

Determinism
-----------
Given the same generation profile, the same upstream revision, and the
same version of ``hletterscriptgen``, the output tree is bit-identical.
The ``generated_at`` field is the one exception — callers should inject a
fixed timestamp for reproducible builds (see ``--generated-at`` on the
``generate`` CLI).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hletterscriptgen import HEBREW_LETTERS, __version__
from hletterscriptgen.extractor import ExtractionError, Glyph, crop_glyph
from hletterscriptgen.generate_profile import (
    GenerateProfile,
    GlyphAnnotation,
    ScanAnnotation,
    WriterAnnotation,
)
from hletterscriptgen.hashing import config_hash
from hletterscriptgen.upstream import (
    UpstreamEntry,
    UpstreamError,
    is_eligible,
    load_entries,
    upstream_pin_from_checkout,
)
from hletterscriptgen.validation import validate_document


class GeneratorError(Exception):
    """Raised when the generator encounters a fatal error."""


class GeneratorWarning(UserWarning):
    """Issued for non-fatal conditions (skipped entries, missing files)."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _variant_id(entry_id: str, letter: str, glyph: GlyphAnnotation) -> str:
    """Deterministic variant identifier derived from the bbox and letter."""
    return f"{entry_id}__{letter}__{glyph.x}_{glyph.y}_{glyph.width}_{glyph.height}"


def _asset_path(entry_id: str, letter: str, glyph: GlyphAnnotation) -> str:
    """POSIX-relative asset path within the writer's output directory."""
    fname = f"{entry_id}__{letter}__{glyph.x}_{glyph.y}_{glyph.width}_{glyph.height}.png"
    return f"glyphs/{letter}/{fname}"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve_scan_path(
    entry: UpstreamEntry,
    upstream_checkout: Path,
) -> Path | None:
    """Return the absolute path of the 'original' scan file, or None.

    Probes the upstream entry's ``files`` list for a file with
    ``role == 'original'``.  Checks ALTO / hOCR sidecar slots first
    (per the deferred open question in sub-PR 1); falls back to
    ``local_path`` on the original file.

    Returns ``None`` when no usable file path can be resolved.
    """
    # Probe for annotation sidecars first (ALTO / hOCR).  The upstream
    # schema defines ``transcription.alto_path`` and ``hocr_path`` slots;
    # all values are currently null in the corpus, but this probe future-
    # proofs the extractor so it can graduate to Option B/C without a
    # code change once sidecars are populated.
    # NOTE: UpstreamEntry models only the ``files[]`` array; sidecar paths
    # live under ``transcription`` which is not yet in the modelled subset.
    # The probe below is a no-op until the upstream model is extended.
    # TODO: extend UpstreamEntry to model transcription.alto_path and
    # transcription.hocr_path, then probe those here before falling back.

    # Fall back to CCA: use the 'original' file's local_path.
    for f in entry.files:
        if f.role == "original" and f.local_path is not None:
            return (upstream_checkout / f.local_path).resolve()
    return None


def _process_writer(
    writer: WriterAnnotation,
    entry_index: dict[str, UpstreamEntry],
    upstream_checkout: Path,
    writer_out_dir: Path,
    profile_raw: dict[str, Any],
    upstream_pin_repo: str,
    upstream_pin_revision: str,
    generated_at: str,
    warnings: list[str],
) -> dict[str, Any]:
    """Build and write the letter_set.v1 document for one writer.

    Returns the letter_set.v1 document dict (already written to disk).
    Appends non-fatal issues to ``warnings``.
    Raises :class:`GeneratorError` on fatal conditions.
    """
    glyph_dir = writer_out_dir / "glyphs"
    letters_map: dict[str, list[dict[str, Any]]] = {}
    observed_licenses: set[str] = set()
    used_entry_ids: set[str] = set()

    for scan in writer.scans:
        entry = entry_index.get(scan.entry_id)
        if entry is None:
            warnings.append(
                f"writer {writer.writer_id!r}: entry_id {scan.entry_id!r} "
                "not found in upstream entries — skipped"
            )
            continue

        if not is_eligible(entry):
            warnings.append(
                f"writer {writer.writer_id!r}: entry_id {scan.entry_id!r} "
                "is not eligible — skipped"
            )
            continue

        scan_path = _resolve_scan_path(entry, upstream_checkout)
        if scan_path is None:
            warnings.append(
                f"writer {writer.writer_id!r}: entry_id {scan.entry_id!r} "
                "has no resolvable scan file — skipped"
            )
            continue

        if not scan_path.is_file():
            warnings.append(
                f"writer {writer.writer_id!r}: scan file not found at "
                f"{scan_path} — skipped"
            )
            continue

        license_expr = entry.rights.license_expression
        if license_expr is None:
            warnings.append(
                f"writer {writer.writer_id!r}: entry_id {scan.entry_id!r} "
                "has no license_expression — skipped"
            )
            continue

        used_entry_ids.add(scan.entry_id)

        for glyph_ann in scan.glyphs:
            if glyph_ann.letter not in HEBREW_LETTERS:
                warnings.append(
                    f"writer {writer.writer_id!r}: entry_id {scan.entry_id!r}: "
                    f"glyph letter {glyph_ann.letter!r} not a recognised "
                    "Hebrew character — skipped"
                )
                continue

            glyph = Glyph(
                x=glyph_ann.x,
                y=glyph_ann.y,
                width=glyph_ann.width,
                height=glyph_ann.height,
            )
            try:
                png_bytes = crop_glyph(scan_path, glyph)
            except ExtractionError as exc:
                warnings.append(
                    f"writer {writer.writer_id!r}: entry_id {scan.entry_id!r}: "
                    f"crop failed ({exc}) — skipped"
                )
                continue

            rel_path = _asset_path(scan.entry_id, glyph_ann.letter, glyph_ann)
            out_file = writer_out_dir / rel_path
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(png_bytes)

            variant: dict[str, Any] = {
                "variant_id": _variant_id(scan.entry_id, glyph_ann.letter, glyph_ann),
                "asset_path": rel_path,
                "checksum_sha256": _sha256_hex(png_bytes),
                "image": {
                    "width_px": glyph_ann.width,
                    "height_px": glyph_ann.height,
                    "format": "png",
                },
                "source": {
                    "scan_entry_id": scan.entry_id,
                    "license": license_expr,
                    "bbox_in_source": {
                        "x": glyph_ann.x,
                        "y": glyph_ann.y,
                        "width": glyph_ann.width,
                        "height": glyph_ann.height,
                    },
                },
                "extracted_at": generated_at,
            }

            letters_map.setdefault(glyph_ann.letter, []).append(variant)
            observed_licenses.add(license_expr)

    if not letters_map:
        raise GeneratorError(
            f"writer {writer.writer_id!r}: no glyphs were successfully extracted; "
            "check warnings for details"
        )

    document: dict[str, Any] = {
        "schema_version": "letter_set.v1",
        "writer_id": writer.writer_id,
        "writer_provenance": {
            "source_repo": upstream_pin_repo,
            "source_entry_ids": sorted(used_entry_ids),
            "attribution_method": writer.attribution_method,
            **({"notes": writer.notes} if writer.notes else {}),
        },
        "generator": {
            "name": "hletterscriptgen",
            "version": __version__,
            "config_hash": config_hash(profile_raw),
        },
        "generated_at": generated_at,
        "upstream": {
            "repo": upstream_pin_repo,
            "revision": upstream_pin_revision,
        },
        "letters": letters_map,
        "license_summary": {
            "licenses": sorted(observed_licenses),
        },
    }

    result = validate_document(document)
    if not result.ok:
        issues = "; ".join(i.format() for i in result.issues)
        raise GeneratorError(
            f"writer {writer.writer_id!r}: generated document failed "
            f"validation: {issues}"
        )

    letter_set_path = writer_out_dir / "letter_set.json"
    letter_set_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return document


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate(
    profile: GenerateProfile,
    profile_raw: dict[str, Any],
    output_dir: Path,
    *,
    generated_at: str | None = None,
) -> list[Path]:
    """Run the full generation pipeline and return paths to letter_set.json files.

    Parameters
    ----------
    profile:
        Parsed generation profile (from :func:`~hletterscriptgen.generate_profile.load_generate_profile`).
    profile_raw:
        The original raw dict from the profile JSON file — used to compute
        ``generator.config_hash`` in the output documents.
    output_dir:
        Root output directory.  Created if it does not exist.
    generated_at:
        ISO 8601 timestamp string to embed in the output documents.
        When ``None`` (default) the current UTC time is used.  Pass a
        fixed value for reproducible builds (see ``--generated-at`` on
        the ``generate`` CLI).

    Returns
    -------
    list[Path]
        Absolute paths to each ``letter_set.json`` written, one per writer.

    Raises
    ------
    GeneratorError
        When the upstream checkout cannot be pinned, no eligible entries
        are found, or a writer's document fails validation.
    UpstreamError
        When the upstream entries file cannot be loaded.
    """
    if generated_at is None:
        generated_at = datetime.now(tz=timezone.utc).isoformat()

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Pin the upstream checkout.
    try:
        pin = upstream_pin_from_checkout(profile.upstream_checkout)
    except Exception as exc:
        raise GeneratorError(
            f"could not pin upstream checkout at "
            f"{profile.upstream_checkout}: {exc}"
        ) from exc

    # 2. Load and index all eligible upstream entries.
    entries_path = profile.upstream_checkout / "data" / "index" / "entries.jsonl"
    try:
        all_entries = list(load_entries(entries_path))
    except UpstreamError as exc:
        raise GeneratorError(f"could not load upstream entries: {exc}") from exc

    entry_index: dict[str, UpstreamEntry] = {e.entry_id: e for e in all_entries}

    # 3. Process each writer.
    warnings: list[str] = []
    output_paths: list[Path] = []

    for writer in profile.writers:
        writer_out_dir = output_dir / writer.writer_id
        writer_out_dir.mkdir(parents=True, exist_ok=True)

        _process_writer(
            writer=writer,
            entry_index=entry_index,
            upstream_checkout=profile.upstream_checkout,
            writer_out_dir=writer_out_dir,
            profile_raw=profile_raw,
            upstream_pin_repo=pin.repo,
            upstream_pin_revision=pin.revision,
            generated_at=generated_at,
            warnings=warnings,
        )
        output_paths.append((writer_out_dir / "letter_set.json").resolve())

    if warnings:
        import warnings as _warnings

        for msg in warnings:
            _warnings.warn(msg, GeneratorWarning, stacklevel=2)

    return output_paths


__all__ = [
    "GeneratorError",
    "GeneratorWarning",
    "generate",
]
