# Contributing

Thanks for considering a contribution to `hletterscriptgen`.

## Scope reminder

This repo holds the **code** that produces per-writer Hebrew letter-glyph
image sets. It does **not** host the letter-set images themselves (those
live in `HeOCR/hletterscript`), and it does **not** ingest upstream scans
(those live in `HeOCR/public-domain-hand-written-hebrew-scans`). Please
keep PRs aligned with that boundary; cross-repo concerns belong upstream
or downstream.

## Development

```bash
python -m pip install -e ".[test]"
python -m pytest
```

Before opening a PR:

```bash
hletterscriptgen validate examples/letter_set/writer_example.json --format json
```

## Pull requests

- Branch names: `feat/...`, `fix/...`, `docs/...`, `refactor/...`, `test/...`.
- Commit subjects: conventional commits (`type(scope): subject`).
- Include a short PR summary listing the files changed and tests run.
- Do not force-push `main`. Do not use `--no-verify`.

## Changing the `letter_set` contract

The `letter_set.v1` schema is a stable public surface. Any change must:

1. Be reflected in `src/hletterscriptgen/schemas/letter_set.schema.json`.
2. Keep `examples/letter_set/writer_example.json` valid against the schema
   (or update it deliberately).
3. Update `docs/letter_set_v1.md` to describe the change.
4. Pass the existing tests in `tests/test_schema.py` and
   `tests/test_validation.py`, plus any new cases the change warrants.

Breaking schema changes require a new schema version (e.g.
`letter_set.v2`); the v1 schema stays in place until downstream consumers
migrate.

## Rights and licensing

- Code contributions are accepted under the MIT license (see [`LICENSE`](LICENSE)).
- Do not commit real glyph image data here; that belongs in
  `HeOCR/hletterscript`.
- Do not propose generator behavior that relicenses, broadens, or
  obscures upstream rights. See [`LICENSE-POLICY.md`](LICENSE-POLICY.md).
