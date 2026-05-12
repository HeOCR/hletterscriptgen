# Repository scope

`hletterscriptgen` is the **code/framework** repository for producing
per-writer Hebrew letter-glyph image sets in the HeOCR system. It is
intentionally narrow.

## Position in the HeOCR system (canonical)

```
public-domain-hand-written-hebrew-scans   (full-page scans, PD / CC / CC-BY)
        │
        ▼
hletterscriptgen   (code/framework — this repo)
        │           extract & group glyphs per writer
        ▼
hletterscript      (per-writer letter-set datasets)
        │
        ▼
hocrsyngen         (composes synthetic Hebrew handwritten pages)
        │
        ▼
hocrgen → HeOCR (mixed)  /  HeOCRsynth (synth-only)
```

Other docs that reference this picture should link here rather than
copy it — only one diagram should ever rot.

## In scope

- Python package, CLI, and schemas that define how a "letter set" is
  represented (`letter_set.v1`).
- Validation tooling that enforces the contract in CI.
- Glyph segmentation, writer grouping, and variant collation pipelines
  (planned — see [roadmap](roadmap.md)).
- Deterministic, reproducible generation runs that emit `letter_set.v1`
  documents, ready for publication elsewhere.

## Out of scope

| Concern | Where it lives |
| --- | --- |
| Hosting page scans and rights records | `HeOCR/public-domain-hand-written-hebrew-scans` |
| Hosting per-writer letter-glyph datasets | `HeOCR/hletterscript` |
| Composing synthetic Hebrew handwritten pages | `HeOCR/hocrsyngen` |
| Dataset orchestration, governance, release assembly, publication | `HeOCR/hocrgen` |
| Mixed-source published OCR/HTR datasets | `HeOCR/HeOCR` |
| Synthetic-only published datasets | `HeOCR/HeOCRsynth` |

## Why these boundaries

- **Code vs. data.** Keeping the generator separate from the published
  glyph datasets keeps the code repo small, reviewable, and easy to
  re-run. Dataset growth lives in `hletterscript` instead of bloating
  this repo's git history.
- **Rights traceability.** Rights are recorded **upstream** per scan and
  carried through **per variant**. Centralizing rights here would
  duplicate that record and risk drift; this repo therefore only
  *propagates* per-variant licenses, never invents them.
- **Composition concerns belong elsewhere.** Composing pages from
  glyphs requires text generation, layout, and degradation — those are
  `hocrsyngen`'s job, not ours.
