# Letter extraction pipeline — DRAFT design

> **Status: DRAFT.** Nothing here is implemented; the `generate` CLI
> exits with `EX_UNAVAILABLE` (`69`). Treat this as a sketch to be
> challenged in M3 (see [`../roadmap.md`](../roadmap.md)).

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

## Open questions

- How is writer identity established when upstream metadata is silent?
  Manual review only, or some lightweight clustering signal?
- What's the right per-variant quality floor (resolution, contrast)
  before we accept a glyph?
- Do near-duplicate variants within a single writer's set get deduped
  here, or carried through with a `near_duplicate_of` reference for
  downstream consumers to decide?

These are the questions M3+ work needs to answer before this pipeline
turns from a sketch into code.
