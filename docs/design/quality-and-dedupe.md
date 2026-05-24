# Quality Metrics and Near-Duplicate Deduplication (M4)

**Status:** Implemented  
**Milestone:** M4  
**Issue:** #22  
**Date:** 2026-05-25

---

## Motivation

The CCA extractor (M3) annotates every connected component that passes the
size and area filters.  Two failure modes degrade downstream HTR training:

1. **Low-quality crops** — crops with very little ink (noise blobs, stray
   marks, artefacts) or fully filled bboxes (ruled lines, bleed-through).
2. **Near-duplicate variants** — the same physical letter glyph annotated more
   than once, or different crops of the same ink stroke from overlapping
   bounding boxes.  Near-dupes inflate the variant count without adding visual
   diversity and can bias classifiers toward specific writers.

M4 addresses both by embedding a per-variant quality metric in the output
schema and running a greedy near-duplicate dedup pass before emitting
`letter_set.json`.

---

## Quality Metric: `ink_ratio`

### Definition

```
ink_ratio = count(foreground pixels in bbox) / (bbox_width × bbox_height)
```

Foreground pixels are those with value > 0 in the Otsu-binarised image
(i.e., ink pixels after `THRESH_BINARY_INV`).

### Rationale

- **Computable with no extra dependencies** — the binarised array is already
  in memory from the crop step.
- **Interpretable** — maps directly onto visual ink density.
- **Actionable** — consumers can threshold on `ink_ratio` to discard near-empty
  or fully-filled crops without re-processing scans.
- **Typical range for legible Hebrew glyphs** — 0.10-0.60; outside this band
  is a quality signal (not a hard filter in M4, left to consumers).

### Implementation

`compute_ink_ratio(binary, glyph)` in `extractor.py`:

```python
crop = binary[glyph.y : glyph.y + glyph.height, glyph.x : glyph.x + glyph.width]
ink_px = int((crop > 0).sum())
return ink_px / (glyph.width * glyph.height)
```

The value is embedded in the `quality` sub-object of every variant in
`letter_set.json` and validated against the updated `letter_set.schema.json`
(where `quality` is now a **required** field on `variant`).

---

## Near-Duplicate Deduplication: dHash + Hamming Distance

### Algorithm

**Step 1 — Compute a 64-bit difference hash (dHash) per crop.**

dHash is a perceptual hash that captures the gradient structure of an image.
For each glyph crop:

1. Resize the crop to `(hash_size + 1) x hash_size` pixels using bilinear
   interpolation (`hash_size = 8` by default → 9 x 8 = 72 pixels).
2. Compare adjacent pixels in each row: for column `c` in row `r`, set bit 1
   if `pixel[r, c] > pixel[r, c+1]`, else 0.
3. Pack all `hash_size²` (64 at default) bits into a single Python `int`.

**Step 2 — Greedy single-pass clustering per letter.**

For each annotated letter (e.g. `'א'`), process variants in arrival order:

- Compare the candidate's dHash against every already-selected
  representative using Hamming distance.
- If the minimum Hamming distance is ≤ `_DEDUP_HAMMING_THRESHOLD` (10),
  the candidate is a near-duplicate of that representative:
  - Keep whichever has the higher `ink_ratio`.
- If no representative is within threshold, add the candidate as a new
  representative.

**Step 3 — Strip the internal `_dhash` key before writing.**

dHash is used only during generation; it is not part of the schema and is
removed from every variant dict before `letter_set.json` is written.

### Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Hash algorithm | dHash | Pure OpenCV (no extra deps); fast; well-suited for binary glyph images |
| Hash size | 8 (64 bits) | Standard; good sensitivity/collision balance for glyph-sized images |
| Hamming threshold | 10 / 64 bits (~15 %) | Conventional loose threshold for perceptual hashing; empirical calibration deferred |
| Dedup scope | Per letter, per writer | Cross-letter dedup is out of scope; cross-writer dedup is a downstream concern |
| Clustering algorithm | Greedy single-pass | O(n²) per letter, but n is small (< 20 variants/letter per writer in practice) |
| Tie-breaking | Higher `ink_ratio` | Proxy for legibility; avoids arbitrary selection |
| dHash in schema | Not included | dHash is a generation-time implementation detail, not a stable output attribute |

### Threshold Calibration

The threshold of 10 / 64 bits is a conservative starting point from the
perceptual-hashing literature.  Empirical calibration against real HeOCR corpus
scans is deferred to a future sub-PR once a labelled near-duplicate test set is
available.  The constant `_DEDUP_HAMMING_THRESHOLD` in `generator.py` is the
single change point.

---

## Schema Changes

`variant` in `letter_set.schema.json` (Draft 2020-12):

- `"quality"` added to the `required` array.
- `"quality"` object added with `"ink_ratio"` as the only required property
  (`number`, range [0.0, 1.0]).
- `additionalProperties: false` on `quality` allows forward extension via
  schema revision.

---

## Public API additions (`extractor.py`)

| Symbol | Type | Description |
|---|---|---|
| `compute_ink_ratio(binary, glyph)` | `float` | Ink fraction in [0.0, 1.0] |
| `compute_dhash(binary, glyph, *, hash_size=8)` | `int` | 64-bit dHash |
| `hamming_distance(a, b)` | `int` | Bit-wise Hamming distance |

All three are exported via `__all__` and documented in the module docstring.

---

## Known Limitations / Out of Scope

- **Hard ink_ratio filtering** — the metric is recorded but no automatic
  drop threshold is applied in M4.  Consumers filter as needed.
- **Cross-writer dedup** — different writers may produce near-identical glyphs;
  dedup is scoped per writer per letter.
- **Clustering quality** — greedy single-pass is order-dependent.  A full
  clustering (e.g. DBSCAN on 64-bit hash space) is deferred.
- **Nikud merging** — diacritical marks are still emitted as separate blobs;
  merging with parent letter bodies deferred to M5.
- **dHash on colour images** — dHash operates on the binarised image; this is
  correct for ink-on-white glyph crops but would need adjustment if the
  pipeline were extended to colour channels.
