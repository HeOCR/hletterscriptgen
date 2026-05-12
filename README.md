# hletterscriptgen

Generator framework for **per-writer Hebrew letter-glyph image sets**, built
on rights-clean upstream scans of handwritten Hebrew documents.

`hletterscriptgen` is part of the [HeOCR](https://github.com/HeOCR) project.
It consumes scan-level records from
[`HeOCR/public-domain-hand-written-hebrew-scans`](https://github.com/HeOCR/public-domain-hand-written-hebrew-scans)
and produces letter-set datasets that land in
[`HeOCR/hletterscript`](https://github.com/HeOCR/hletterscript). Downstream,
[`HeOCR/hocrsyngen`](https://github.com/HeOCR/hocrsyngen) composes those
glyphs into synthetic Hebrew handwritten pages, which
[`HeOCR/hocrgen`](https://github.com/HeOCR/hocrgen) folds into
[`HeOCR/HeOCR`](https://github.com/HeOCR/HeOCR) and
[`HeOCR/HeOCRsynth`](https://github.com/HeOCR/HeOCRsynth).

## Repository scope

This repository contains the **code, schemas, and contracts** that produce
letter sets. It does **not** host the letter-set image data; that lives in
`HeOCR/hletterscript`.

What lives here:

- A Python package and CLI (`hletterscriptgen`).
- The `letter_set.v1` JSON Schema and a fixture example
  (`examples/letter_set/writer_example.json`).
- Validation tooling (`hletterscriptgen validate`).
- CI that enforces schema and tooling invariants.
- Licensing policy and rights-carryover rules
  ([`LICENSE-POLICY.md`](LICENSE-POLICY.md)).

What does **not** live here:

- Actual extracted glyph images (→ `HeOCR/hletterscript`).
- Page-scan ingestion or rights curation (→
  `HeOCR/public-domain-hand-written-hebrew-scans`).
- Document composition (→ `HeOCR/hocrsyngen`).
- Dataset orchestration, governance, release assembly, or publication (→
  `HeOCR/hocrgen` / `HeOCR/HeOCR` / `HeOCR/HeOCRsynth`).

## Position in the HeOCR system

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

## Install

```bash
python -m pip install -e ".[test]"
```

Requires Python 3.11+.

## CLI

```bash
hletterscriptgen version
hletterscriptgen schema --format json
hletterscriptgen validate examples/letter_set/writer_example.json
hletterscriptgen validate examples/letter_set/writer_example.json --format json
```

The `generate` subcommand is reserved for the upcoming extraction pipeline
and is not yet implemented; see [`docs/roadmap.md`](docs/roadmap.md).

## The `letter_set.v1` contract

The bundled JSON Schema describes a per-writer letter set:

- One document per **writer**.
- `letters` maps each Hebrew letter (base or final form, `U+05D0`–`U+05EA`)
  to one or more **variants** extracted from upstream scans by that writer.
- Each variant carries an `asset_path`, a SHA-256 checksum, image metadata,
  and **per-variant source rights**, so license evidence flows through from
  upstream into any downstream composition.

See [`docs/letter_set_v1.md`](docs/letter_set_v1.md) for the full
explanation and field-by-field notes.

## Licensing

- Code in this repository: MIT (see [`LICENSE`](LICENSE)).
- Generated letter sets: carry per-variant upstream rights — see
  [`LICENSE-POLICY.md`](LICENSE-POLICY.md). The generator does not
  relicense glyphs.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). For agent collaborators, see
[`AGENTS.md`](AGENTS.md).
