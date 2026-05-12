# Architecture

The current architecture is a thin, contract-first scaffolding. Real
extraction logic lands in later milestones — see [roadmap](roadmap.md).

## Code layout

```
src/hletterscriptgen/
├── __init__.py          # version + schema id
├── __main__.py          # `python -m hletterscriptgen`
├── cli.py               # argparse CLI: version | schema | validate | generate
├── validation.py        # Draft 2020-12 validator helpers
└── schemas/
    └── letter_set.schema.json   # packaged letter_set.v1
examples/
└── letter_set/
    └── writer_example.json      # fixture exercised by CI
tests/
├── test_schema.py       # schema is valid Draft 2020-12
├── test_validation.py   # example validates; mutated fixtures fail
└── test_cli.py          # CLI subcommand smoke checks
```

## Validation pipeline

1. `hletterscriptgen.validation.load_schema()` loads the bundled
   `letter_set.schema.json` via `importlib.resources`.
2. `validate_document()` and `validate_path()` build a
   `jsonschema.Draft202012Validator` and emit a `ValidationResult` with
   sorted, path-tagged issues.
3. The CLI's `validate` subcommand renders that result as text or JSON,
   exiting `0` on success and `1` on contract violations.

CI runs the same validator over the packaged example fixture to keep
the contract honest as the schema evolves.

## Future generator pipeline (planned)

Once segmentation lands, the generator will:

1. Read a release-profile-style configuration declaring which upstream
   scan entries to process and which writers to group them under.
2. For each writer:
   1. Segment glyphs from each contributing scan.
   2. Map glyphs to Hebrew letters (base + final forms).
   3. Emit one or more `variant` entries per letter, each with
      checksum, bounding box, image metadata, and **per-variant
      upstream rights**.
3. Aggregate per-variant licenses into `license_summary.licenses`.
4. Write a `letter_set.v1` JSON document per writer, plus the
   underlying image assets, into a deterministic working directory.
5. Publish the resulting tree to `HeOCR/hletterscript` via the
   downstream-handoff flow.

None of this is implemented yet; the `generate` CLI exits with a
deliberate "not yet implemented" message.
