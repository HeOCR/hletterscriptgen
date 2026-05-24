# HTR tooling landscape — reference

A survey of open-source layout analysis and HTR tools relevant to the
`hletterscriptgen` pipeline, specifically for historical Hebrew manuscripts.
Recorded 2026-05-24 as background for M3+ segmentation decisions.

Standard layout analysis tools fail on historical Hebrew because they assume
clean, LTR, printed text.  Historical Hebrew involves RTL writing, complex
multi-column layouts (e.g. Talmud + Rashi commentary zones), marginalia, and
heavily degraded parchment.

---

## Kraken + eScriptorium

**Kraken** is the leading open-source OCR/HTR engine for historical documents
and non-Latin scripts.  **eScriptorium** is its web-based annotation and
training UI.

- RTL and BiDi text native.
- Produces **polygon baseline masks** rather than rectangular bounding boxes —
  essential for sloping or intersecting handwritten lines.
- Exports ALTO-XML and PAGE-XML: the standard sidecar formats that the upstream
  HASH entry schema already anticipates (`alto_path`, `hocr_path`).

Links:
- Kraken: <https://github.com/mittagessen/kraken>
- eScriptorium: <https://github.com/scripta-studio/escriptorium>
- Docker image available for self-hosted deployment.

### Pre-trained Hebrew / Genizah models

Two substantial projects have released open-source Kraken models trained on
Cairo Genizah fragments.  These give a high-accuracy first pass with no
additional training data:

| Project | Model type | Repository |
|---------|-----------|------------|
| **MiDRASH Project** | Baseline segmentation + HTR, Cairo Genizah | <https://github.com/MiDRASH-Project> |
| **Princeton Geniza Project — HTR4PGP** | Baseline segmentation + HTR, Princeton Geniza Lab | <https://github.com/Princeton-CDH/geniza> |

**Connection to M3:**  The upstream HASH corpus already includes Cairo Genizah
fragments (Bodleian T-S items, Halper items) and has `openn__cairo_genizah` as
a candidate source.  The MiDRASH and HTR4PGP models apply directly to that
material.  If the upstream corpus gains ALTO/PAGE-XML sidecars produced from
these models, the `segmentation-approach.md` Option B path (consume
pre-annotated bounding boxes) becomes viable without any new tooling investment
in this repo.

---

## Eynollah (Qurator-SPK)

Command-line layout analysis tool using pixel-wise deep learning segmentation.

- Classifies every page pixel into up to 10 classes: background, text region,
  text line, header, image, separator, marginalia, table.
- Strongest at multi-zone layouts — e.g. detecting the Rashi commentary columns
  wrapping a central Talmudic text before individual line extraction.
- Output: PAGE-XML with polygon coordinates for every region and line.
- Repo: <https://github.com/qurator-spk/eynollah>

---

## LayoutParser

Python library providing a unified API for deep learning document image
analysis (Mask R-CNN, Faster R-CNN, etc.).

- Suitable for building a custom bounding-box detection pipeline: annotate a
  few dozen pages, train a model, run batch inference.
- Repo / docs: <https://layout-parser.github.io/>

---

## dhSegment (and Doc-UFCN)

U-Net pixel-wise semantic segmentation — robust against degraded, stained, or
bleed-through manuscript images.

- Classifies every pixel as background, text line, or page boundary; output
  mask is trivially post-processed into bounding boxes or polygons.
- Best suited to the most damaged material: heavily degraded Genizah fragments
  and the oldest items in the corpus.
- dhSegment repo: <https://github.com/dhlab-epfl/dhSegment>
- Doc-UFCN: <https://github.com/soduco/paper-ufcn-icdar21>

---

## HTR-United catalog

Community catalog of published HTR training datasets and model registries.

- Discovery resource: may surface Hebrew training sets not already tracked in
  the upstream HASH source list.
- URL: <https://htr-united.github.io/catalog.html>

---

## Relationship to current M3 decisions

The segmentation approach chosen for M3 is connected-component analysis via
`opencv-python-headless` (Option A in
[`design/segmentation-approach.md`](design/segmentation-approach.md)).  That
choice was made because the upstream corpus ships no annotation sidecars.

The tools above do not change the M3 decision, but they do change the
post-M3 picture for Option C (pre-trained segmentation model):

- Option C was previously described as "deferred indefinitely" because it adds
  nothing without ground-truth labels.
- Kraken + MiDRASH/HTR4PGP are Hebrew-specific, pre-trained, and ready to
  produce ALTO/PAGE-XML annotations over the existing corpus **today** — no
  new training data is required.
- If those annotations are added as upstream sidecars (the HASH schema already
  has the `alto_path`/`hocr_path` slots), the M3 extractor's deferred open
  question 1 ("probe `alto_path` first, fall back to CCA") becomes immediately
  actionable.

The practical upgrade path is: eScriptorium + MiDRASH model → produce
PAGE-XML annotations → commit them as upstream sidecars → the extractor probes
`alto_path` and gets polygon-quality line coordinates instead of CCA blobs.
This is a pure upstream concern, but it is worth tracking here because it
directly improves glyph quality in M3/M4 output.
