# Architecture

The current architecture is a thin, contract-first scaffolding. Real
extraction logic lands in later milestones — see [roadmap](roadmap.md)
and the draft [letter-extraction design](design/letter_extraction.md).

## Code layout

```
src/hletterscriptgen/
├── __init__.py          # version, schema id, exported constants
├── __main__.py          # `python -m hletterscriptgen`
├── cli.py               # argparse CLI: version | schema | validate | generate
├── validation.py        # Draft 2020-12 schema + cross-field validation
├── py.typed             # PEP 561 typing marker
└── schemas/
    └── letter_set.schema.json   # packaged letter_set.v1
examples/
└── letter_set/
    └── writer_example.json      # fixture exercised by CI
tests/
├── test_schema.py       # schema validity + package-constant alignment
├── test_validation.py   # example validates; mutated fixtures fail
└── test_cli.py          # CLI subcommand smoke (mostly in-process)
```

## Validation pipeline

Validation runs in two stages — see
[`validation.py`](../src/hletterscriptgen/validation.py) for the
authoritative version.

1. **Schema stage.**
   `hletterscriptgen.validation.load_schema()` loads the bundled
   `letter_set.schema.json` via `importlib.resources`. A
   `jsonschema.Draft202012Validator` (with `FORMAT_CHECKER` enabled, so
   `date-time` and `uri` strings are actually checked) emits
   path-tagged structural errors.
2. **Cross-field stage.** Only if the schema stage is clean, a custom
   check verifies invariants that JSON Schema cannot express:
   - `license_summary.licenses` (as a set) equals the set of
     `source.license` across all variants.
   - Every variant's `source.scan_entry_id` is listed in
     `writer_provenance.source_entry_ids`.
   - No variant's `asset_path` contains a `..` segment.

The CLI's `validate` subcommand renders the combined result as text or
JSON, exiting `0` on success and `1` on contract violations. CI runs
the same validator over the packaged example fixture to keep the
contract honest as the schema evolves.
