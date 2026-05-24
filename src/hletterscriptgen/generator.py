"""End-to-end glyph extraction pipeline (M3/M4).

Orchestrates the full generate flow:

1. Pin the upstream checkout revision.
2. Load and index all eligible upstream entries.
3. For each writer → each scan → each annotated glyph:
   a. Look up the upstream entry; skip ineligible entries (warn).
   b. Resolve the scan file path from the upstream checkout.
   c. Binarise the scan once, then crop/hash/measure each glyph.
   d. Accumulate variant dicts in memory (PNG bytes held, not yet written).
4. Per letter: deduplicate near-duplicate variants by 64-bit dHash
   (Hamming ≤ :data:`_DEDUP_HAMMING_THRESHOLD`); keep highest ``ink_ratio``.
5. Write only the surviving PNG assets to the output tree.
6. Build and validate the ``letter_set.v1`` document for each writer.
7. Write ``letter_set.json`` to the writer's output directory.

Output tree structure::

    <output_dir>/
      <writer_id>/
        letter_set.json
        glyphs/
          <letter>/
            <entry_id>@<letter>@<x>_<y>_<w>_<h>.png

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
import warnings as _warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hletterscriptgen import HEBREW_LETTERS, __version__
from hletterscriptgen.extractor import (
    ExtractionError,
    Glyph,
    binarize_scan,
    compute_dhash,
    compute_ink_ratio,
    crop_binary,
    hamming_distance,
)
from hletterscriptgen.generate_profile import (
    GenerateProfile,
    GlyphAnnotation,
    WriterAnnotation,
)
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
    """Deterministic variant identifier derived from the bbox and letter.

    Uses ``@`` as a separator between the entry_id, letter, and coordinates
    so the boundary is unambiguous even when entry_ids themselves contain
    double-underscores.
    """
    return f"{entry_id}@{letter}@{glyph.x}_{glyph.y}_{glyph.width}_{glyph.height}"


def _asset_path(entry_id: str, letter: str, glyph: GlyphAnnotation) -> str:
    """POSIX-relative asset path within the writer's output directory."""
    fname = f"{entry_id}@{letter}@{glyph.x}_{glyph.y}_{glyph.width}_{glyph.height}.png"
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


# Hamming-distance threshold for near-duplicate dHash clustering.  Two glyphs
# whose hashes differ by ≤ this many bits are considered near-duplicates; the
# one with the higher ink_ratio is kept.  10 / 64 bits ≈ 15 % of bits differ,
# which is the conventional loose threshold for perceptual-hash deduplication.
_DEDUP_HAMMING_THRESHOLD: int = 10


def _dedup_letter_variants(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a deduplicated copy of one letter's candidate variant list.

    Clusters variants by 64-bit dHash using a greedy single-pass algorithm:
    for each variant (in arrival order), check whether it falls within
    :data:`_DEDUP_HAMMING_THRESHOLD` Hamming bits of any already-selected
    representative.

    * If it **matches** an existing representative and has a **higher**
      ``ink_ratio``, the representative's payload (variant_id, asset_path,
      checksum, quality, source, png bytes, …) is replaced with the
      candidate's — but the **cluster-centre hash** (the original
      representative's ``_dhash``) is **preserved**.  This prevents the
      cluster centre from drifting across successive updates, which would
      otherwise cause a chain A ≈ B ≈ C (but A ≁ C) to incorrectly absorb
      C into A's cluster.
    * If it **matches** but has an equal or lower ``ink_ratio``, the existing
      representative is kept unchanged.
    * If it does **not match** any representative, it starts a new cluster.

    Internal keys (``_dhash``, ``_png_bytes``) are **not** stripped here;
    the caller is responsible for stripping them and writing PNG files after
    this function returns.

    Parameters
    ----------
    variants:
        List of variant dicts, each carrying temporary ``_dhash`` (int) and
        ``_png_bytes`` (bytes) keys alongside the schema-visible fields.

    Returns
    -------
    list[dict[str, Any]]
        Deduplicated list retaining all input keys (including ``_dhash`` and
        ``_png_bytes``).
    """
    representatives: list[dict[str, Any]] = []

    for candidate in variants:
        c_hash = candidate["_dhash"]
        c_ink = candidate["quality"]["ink_ratio"]
        matched = False
        for rep in representatives:
            if hamming_distance(c_hash, rep["_dhash"]) <= _DEDUP_HAMMING_THRESHOLD:
                if c_ink > rep["quality"]["ink_ratio"]:
                    cluster_hash = rep["_dhash"]  # preserve cluster centre
                    rep.update(candidate)
                    rep["_dhash"] = cluster_hash  # restore after bulk update
                matched = True
                break
        if not matched:
            representatives.append(dict(candidate))

    return representatives


def _extract_variants(
    writer: WriterAnnotation,
    entry_index: dict[str, UpstreamEntry],
    upstream_checkout: Path,
    writer_out_dir: Path,
    generated_at: str,
    pending_warnings: list[str],
) -> tuple[dict[str, list[dict[str, Any]]], set[str], set[str]]:
    """Crop, deduplicate, and write glyph variants for one writer.

    Returns ``(letters_map, observed_licenses, used_entry_ids)``.
    Non-fatal issues (missing entries, ineligible scans, crop failures) are
    appended to ``pending_warnings``.

    Pipeline order within this function:

    1. Accumulate all candidate variant dicts in memory, holding PNG bytes
       under the temporary ``_png_bytes`` key (no disk writes yet).
    2. Deduplicate per letter via :func:`_dedup_letter_variants`.
    3. **Only then** write the surviving PNGs to disk, so that no files are
       created for variants eliminated by dedup.
    4. Derive ``used_entry_ids`` and ``observed_licenses`` from the survivors,
       so that entries or licenses contributed solely by deduped-out variants
       are not listed in the output manifest.

    The scan image is binarised once per scan file; all glyph crops for that
    scan share the same binary array, avoiding redundant I/O.
    """
    letters_map: dict[str, list[dict[str, Any]]] = {}

    for scan in writer.scans:
        entry = entry_index.get(scan.entry_id)
        if entry is None:
            pending_warnings.append(
                f"writer {writer.writer_id!r}: entry_id {scan.entry_id!r} "
                "not found in upstream entries — skipped"
            )
            continue

        if not is_eligible(entry):
            pending_warnings.append(
                f"writer {writer.writer_id!r}: entry_id {scan.entry_id!r} "
                "is not eligible — skipped"
            )
            continue

        scan_path = _resolve_scan_path(entry, upstream_checkout)
        if scan_path is None:
            pending_warnings.append(
                f"writer {writer.writer_id!r}: entry_id {scan.entry_id!r} "
                "has no resolvable scan file — skipped"
            )
            continue

        if not scan_path.is_file():
            pending_warnings.append(
                f"writer {writer.writer_id!r}: scan file not found at "
                f"{scan_path} — skipped"
            )
            continue

        license_expr = entry.rights.license_expression
        if license_expr is None:
            pending_warnings.append(
                f"writer {writer.writer_id!r}: entry_id {scan.entry_id!r} "
                "has no license_expression — skipped"
            )
            continue

        # Binarise the scan once; reuse the binary array for all glyphs in
        # this scan to avoid re-loading and re-thresholding per glyph.
        try:
            binary = binarize_scan(scan_path)
        except ExtractionError as exc:
            pending_warnings.append(
                f"writer {writer.writer_id!r}: entry_id {scan.entry_id!r}: "
                f"could not binarize scan ({exc}) — skipped"
            )
            continue

        for glyph_ann in scan.glyphs:
            if glyph_ann.letter not in HEBREW_LETTERS:
                pending_warnings.append(
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
                png_bytes = crop_binary(binary, glyph)
            except ExtractionError as exc:
                pending_warnings.append(
                    f"writer {writer.writer_id!r}: entry_id {scan.entry_id!r}: "
                    f"crop failed ({exc}) — skipped"
                )
                continue

            ink = compute_ink_ratio(binary, glyph)
            dhash = compute_dhash(binary, glyph)
            rel_path = _asset_path(scan.entry_id, glyph_ann.letter, glyph_ann)

            variant: dict[str, Any] = {
                # Internal keys stripped after dedup + file write (not in schema).
                "_dhash": dhash,
                "_png_bytes": png_bytes,
                # Schema-visible fields.
                "variant_id": _variant_id(scan.entry_id, glyph_ann.letter, glyph_ann),
                "asset_path": rel_path,
                "checksum_sha256": _sha256_hex(png_bytes),
                "image": {
                    "width_px": glyph_ann.width,
                    "height_px": glyph_ann.height,
                    "format": "png",
                },
                "quality": {
                    "ink_ratio": ink,
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
            if glyph_ann.notes is not None:
                variant["notes"] = glyph_ann.notes

            letters_map.setdefault(glyph_ann.letter, []).append(variant)

    # Dedup: collapse near-duplicate variants per letter (Hamming ≤ threshold).
    # Warn when any are dropped so callers have visibility into data loss.
    for letter in letters_map:
        pre_count = len(letters_map[letter])
        letters_map[letter] = _dedup_letter_variants(letters_map[letter])
        dropped = pre_count - len(letters_map[letter])
        if dropped:
            pending_warnings.append(
                f"writer {writer.writer_id!r}: dropped {dropped} near-duplicate "
                f"variant(s) for letter {letter!r} "
                f"(dHash Hamming <= {_DEDUP_HAMMING_THRESHOLD})"
            )

    # Write only surviving variants to disk, then strip internal keys.
    # Doing this after dedup guarantees no orphaned PNG files for eliminated variants.
    for variants in letters_map.values():
        for variant in variants:
            png = variant.pop("_png_bytes")
            variant.pop("_dhash")
            out_file = writer_out_dir / variant["asset_path"]
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(png)

    # Derive from survivors only: entries or licenses contributed solely by
    # deduped-out variants must not appear in the manifest.
    used_entry_ids: set[str] = {
        v["source"]["scan_entry_id"]
        for variants in letters_map.values()
        for v in variants
    }
    observed_licenses: set[str] = {
        v["source"]["license"]
        for variants in letters_map.values()
        for v in variants
    }

    return letters_map, observed_licenses, used_entry_ids


def _build_document(
    writer: WriterAnnotation,
    letters_map: dict[str, list[dict[str, Any]]],
    observed_licenses: set[str],
    used_entry_ids: set[str],
    upstream_pin_repo: str,
    upstream_pin_revision: str,
    config_hash: str,
    generated_at: str,
) -> dict[str, Any]:
    """Assemble and return the letter_set.v1 document dict for one writer."""
    return {
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
            "config_hash": config_hash,
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


def _process_writer(
    writer: WriterAnnotation,
    entry_index: dict[str, UpstreamEntry],
    upstream_checkout: Path,
    writer_out_dir: Path,
    upstream_pin_repo: str,
    upstream_pin_revision: str,
    config_hash: str,
    generated_at: str,
    pending_warnings: list[str],
) -> dict[str, Any]:
    """Build and write the letter_set.v1 document for one writer.

    Returns the letter_set.v1 document dict (already written to disk).
    Appends non-fatal issues to ``pending_warnings``.
    Raises :class:`GeneratorError` on fatal conditions.
    """
    letters_map, observed_licenses, used_entry_ids = _extract_variants(
        writer=writer,
        entry_index=entry_index,
        upstream_checkout=upstream_checkout,
        writer_out_dir=writer_out_dir,
        generated_at=generated_at,
        pending_warnings=pending_warnings,
    )

    if not letters_map:
        raise GeneratorError(
            f"writer {writer.writer_id!r}: no glyphs were successfully extracted; "
            "check warnings for details"
        )

    document = _build_document(
        writer=writer,
        letters_map=letters_map,
        observed_licenses=observed_licenses,
        used_entry_ids=used_entry_ids,
        upstream_pin_repo=upstream_pin_repo,
        upstream_pin_revision=upstream_pin_revision,
        config_hash=config_hash,
        generated_at=generated_at,
    )

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
    output_dir: Path,
    *,
    generated_at: str | None = None,
) -> list[Path]:
    """Run the full generation pipeline and return paths to letter_set.json files.

    Parameters
    ----------
    profile:
        Parsed generation profile (from
        :func:`~hletterscriptgen.generate_profile.load_generate_profile`).
        The profile's ``config_hash`` field is embedded in output documents.
    output_dir:
        Root output directory.  Created if it does not exist.
    generated_at:
        ISO 8601 timestamp string to embed in the output documents.
        When ``None`` (default) the current UTC time is used (second
        precision, no microseconds).  Pass a fixed value for reproducible
        builds (see ``--generated-at`` on the ``generate`` CLI).

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
        generated_at = datetime.now(tz=UTC).replace(microsecond=0).isoformat()

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Pin the upstream checkout.
    try:
        pin = upstream_pin_from_checkout(profile.upstream_checkout)
    except (UpstreamError, OSError) as exc:
        raise GeneratorError(
            f"could not pin upstream checkout at "
            f"{profile.upstream_checkout}: {exc}"
        ) from exc

    # 2. Load and index all upstream entries.
    entries_path = profile.upstream_checkout / "data" / "index" / "entries.jsonl"
    try:
        all_entries = list(load_entries(entries_path))
    except UpstreamError as exc:
        raise GeneratorError(f"could not load upstream entries: {exc}") from exc

    entry_index: dict[str, UpstreamEntry] = {e.entry_id: e for e in all_entries}

    # 3. Process each writer.
    pending_warnings: list[str] = []
    output_paths: list[Path] = []

    for writer in profile.writers:
        writer_out_dir = output_dir / writer.writer_id
        writer_out_dir.mkdir(parents=True, exist_ok=True)

        _process_writer(
            writer=writer,
            entry_index=entry_index,
            upstream_checkout=profile.upstream_checkout,
            writer_out_dir=writer_out_dir,
            upstream_pin_repo=pin.repo,
            upstream_pin_revision=pin.revision,
            config_hash=profile.config_hash,
            generated_at=generated_at,
            pending_warnings=pending_warnings,
        )
        output_paths.append((writer_out_dir / "letter_set.json").resolve())

    if pending_warnings:
        for msg in pending_warnings:
            _warnings.warn(msg, GeneratorWarning, stacklevel=2)

    return output_paths


__all__ = [
    "GeneratorError",
    "GeneratorWarning",
    "generate",
]
