# Letter extraction pipeline — DRAFT design

> **Status: DRAFT — segmentation approach resolved.**  The `generate` CLI still exits with
> `EX_UNAVAILABLE` (`69`); extraction is not yet implemented.  The open question about *how*
> glyphs are segmented has been answered in
> [`segmentation-approach.md`](segmentation-approach.md): connected-component analysis via
> `opencv-python-headless` (Option A), chosen because the upstream corpus ships no annotation
> sidecars.  See [`../roadmap.md`](../roadmap.md) for the full M3 scope.

## Goal

Turn rights-clean handwritten Hebrew page scans (upstream:
`HeOCR/public-domain-hand-written-hebrew-scans`) into per-writer
`letter_set.v1` documents plus their referenced glyph image assets.

## Sketch

1. **Configuration.** Read a release-profile-style configuration that
   declares which upstream scan entries to process and which writers to
   group them under. The configuration is hashed (SHA-256, canonical
   JSON) into `generator.config_hash`.
2. **Upstream pin.** Resolve the upstream repo + revision and record
   them in `upstream.repo` / `upstream.revision`. The run **fails** if
   the working upstream revision is dirty or untagged.
3. **Per-writer extraction.** For each writer:
   1. Segment glyphs from each contributing scan.
   2. Map glyphs to Hebrew letters (base + final forms, U+05D0..U+05EA).
   3. Emit one or more `variant` entries per letter, each with
      checksum, bounding box, image metadata, and **per-variant
      upstream rights** copied from the upstream entry.
4. **License summary.** Aggregate per-variant licenses into
   `license_summary.licenses`. The validator will reject mismatches.
5. **Materialize.** Write a `letter_set.v1` JSON document per writer,
   plus the underlying image assets, into a deterministic working
   directory.
6. **Handoff.** Package the tree for publication into
   `HeOCR/hletterscript`. The exact handoff format is also a draft —
   see [`../downstream_handoff.md`](../downstream_handoff.md).

## Design decisions (closed in issue #16)

The three open questions from the original draft were resolved in issue #16 before M3 coding began:

- **Writer identity when upstream metadata is silent** → manual-review-only for M3; the
  generator consumes a `WriterProfile`, never infers identity (decision D1).
- **Per-variant quality floor** → bounding box ≥ `MIN_GLYPH_PX` (16 × 16 px), named constant;
  no contrast or sharpness metrics until M4 (decision D2).
- **Near-duplicate variants** → emit all; deduplication is M4 (decision D3).

**Segmentation approach** → connected-component analysis (`opencv-python-headless`); see
[`segmentation-approach.md`](segmentation-approach.md) for the full decision record and
open questions deferred to sub-PR 2.
