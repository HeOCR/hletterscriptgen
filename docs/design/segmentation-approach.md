# Segmentation approach — decision record

> **Status: DECIDED** — M3 sub-PR 1 spike.
> See [`letter_extraction.md`](letter_extraction.md) for the broader extraction pipeline design.

## Decision: Option A — Connected-component analysis

The upstream corpus ships **no annotation sidecars of any kind** for any current entry.
Option B (pre-annotated bounding boxes) is therefore unavailable, and Option A
(connected-component analysis with OpenCV) is selected as the M3 segmentation approach.
Option C (pre-trained segmentation model) is deferred indefinitely; it is heavier and less
deterministic than CCA, and adds nothing when the corpus lacks ground-truth labels for
training or evaluation.

---

## Evidence from the upstream corpus

Investigation target: `HeOCR/public-domain-hand-written-hebrew-scans` (GitHub, inspected via
`gh api` — local clone not present at time of spike).

| Finding | Detail |
|---------|--------|
| Total entries in `data/index/entries.jsonl` | 60 |
| `transcription.status` distribution | `"none"`: 60 / 60 |
| Non-null `alto_path` | 0 / 60 |
| Non-null `hocr_path` | 0 / 60 |
| Non-null `text_path` | 0 / 60 |
| Unique `files[].role` values across all entries | `"original"` only |
| Scan directories inspected (`data/scans/`) | `commons__begani_netatikha` (representative sample) — contains only the JPEG scan, no sidecars |

The upstream `entry.schema.json` defines `transcription.alto_path` and `transcription.hocr_path`
fields, so the schema anticipates future annotation additions. All values are `null` today.
The file-role enum (`original`, `normalized`, `thumbnail`, `transcription`, `metadata`) includes a
`transcription` role, but zero entries exercise it.

Source files consulted:
- `HeOCR/public-domain-hand-written-hebrew-scans/schemas/entry.schema.json`
- `HeOCR/public-domain-hand-written-hebrew-scans/data/index/entries.jsonl`
- `HeOCR/public-domain-hand-written-hebrew-scans/data/scans/commons__begani_netatikha/`

---

## Option A specification

### Library

`opencv-python-headless` — the display-free build of OpenCV; no GUI dependency needed for a
batch pipeline. Added to `[project.optional-dependencies]` as group `cv` in `pyproject.toml`
so callers that only consume schema/validation code do not pull in the CV stack.

### Algorithm

1. **Load** the scan image (`cv2.imread`).
2. **Greyscale** conversion (`cv2.cvtColor` → `COLOR_BGR2GRAY`).
3. **Binarise** with Otsu's method (`cv2.threshold` with `THRESH_BINARY_INV + THRESH_OTSU`).
   Inversion puts ink pixels as foreground (255) on white background (0), which is what
   `connectedComponentsWithStats` expects.
4. **Connected-component labelling** (`cv2.connectedComponentsWithStats`) returns per-blob
   bounding boxes and pixel counts in one pass.
5. **Filter** by the 16 × 16 px quality floor (named constant `MIN_GLYPH_PX = 16`, per issue #16
   decision D2) and optionally by an upper-area ceiling to drop page-level noise blobs.
6. **Crop** each surviving bounding box from the binarised image and write to the output tree.

### Known failure modes for Hebrew handwriting

| Failure mode | Cause | Severity |
|---|---|---|
| **Touching letters** | Ink bridges between adjacent letters merge into one blob | High — common in cursive and semi-cursive styles |
| **Nikud (diacritical marks)** | Dots (shva, dagesh, holam, …) form separate tiny blobs or merge with the adjacent letter body | Medium — most marks fall below the 16 × 16 px floor, but some are letter-distinctive |
| **Final forms** (ך ם ן ף ץ) | Final forms have extended descenders that may bridge into the line below on dense pages | Low–medium |
| **Ligatures and ambiguous strokes** | Some scribal styles ligate letters that are not officially ligated (e.g. lamed-alef) | Low for standard square script, higher for Rashi script |
| **Skewed or warped pages** | Rotation stretches bounding boxes; a deskew step before binarisation would mitigate | Low if corpus images are reasonably straight |
| **Margin noise** | Stamps, ruled lines, bleed-through from verso can produce large foreground blobs | Mitigated by upper-area ceiling filter |

These failure modes are acceptable for M3 (an MVP extraction, not a quality-filtered set).
M4 deduplication will absorb some touching-letter artefacts. A more robust segmenter
(e.g. a line-level projection-profile split before CCA, or a pre-trained model) can be
introduced post-M3 without changing the output schema.

---

## Open questions deferred to sub-PR 2

1. **Upstream annotation probe** — the upstream schema already has `alto_path` / `hocr_path`
   slots. Should the extractor probe those paths first and fall back to CCA only when they
   are null? This would let the corpus graduate to Option B incrementally without a code
   change. Decision deferred to sub-PR 2 when the extractor is written.

2. **Deskew pre-processing** — should a deskew step (e.g. Hough-line-based rotation
   correction) run before binarisation? Deferred to sub-PR 2; depends on the actual scan
   quality distribution in the corpus.

3. **Upper-area ceiling value** — what pixel-area threshold separates a large glyph from a
   noise blob? Needs empirical calibration against real scans. Deferred to sub-PR 2.

4. **Nikud handling** — should the extractor attempt to merge diacritic blobs with their
   parent letter glyph? Out of scope for M3 (emit raw CCA output), but the open question
   should be recorded for M4.
