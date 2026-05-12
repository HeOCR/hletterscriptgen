# Downstream handoff

Letter sets produced here are **published** to
[`HeOCR/hletterscript`](https://github.com/HeOCR/hletterscript). From
there, [`HeOCR/hocrsyngen`](https://github.com/HeOCR/hocrsyngen) consumes
them to compose synthetic Hebrew handwritten pages, which
[`HeOCR/hocrgen`](https://github.com/HeOCR/hocrgen) folds into
[`HeOCR/HeOCR`](https://github.com/HeOCR/HeOCR) (mixed releases) and
[`HeOCR/HeOCRsynth`](https://github.com/HeOCR/HeOCRsynth)
(synth-only releases).

## What `hletterscriptgen` ships

For each writer, the generator emits:

- One `letter_set.v1` JSON document (the canonical record).
- A directory of glyph image assets referenced by `asset_path`.

Together these form a self-contained letter-set tree that can be moved
into `hletterscript` without re-resolving paths.

## Boundary with `hletterscript`

- The publishing flow only commits **artifacts** to `hletterscript`:
  the `letter_set.v1` JSON document(s) and the referenced glyph
  images. The generation tooling itself stays in this repo.
- `hletterscript` will run a thin schema-validation CI of its own
  against the same `letter_set.v1` schema bundled here. Consumers
  should depend on the schema id (`letter_set.v1`) rather than on
  unstable internals.
- If the schema evolves, the bundled JSON Schema in
  `src/hletterscriptgen/schemas/` is the source of truth and should be
  republished to consumers via package release.

## Boundary with `hocrsyngen`

- `hocrsyngen` consumes letter sets as **inputs**. It must read
  per-variant `source.license` before composing aggregate outputs and
  must propagate the strictest applicable license to its own outputs.
- `hocrsyngen` does not write back into `hletterscript`; new variants
  or writers are produced here and published there.

## Boundary with `hocrgen` and the HeOCR / HeOCRsynth releases

- Release governance, dedupe, review queues, splits, and publication
  belong to `hocrgen`. Nothing in this repo participates in those
  flows.
- License-based release filtering (e.g. SA-only bundles vs.
  permissive-only bundles) is `hocrgen`'s decision and is performed
  against per-variant rights surfaced by this contract.
