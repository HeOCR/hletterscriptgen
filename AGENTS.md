# AGENTS.md

Static instructions for agents working in this repository. Keep dynamic
status (current focus, next actions) in `.agent-plan.md` when one exists;
keep human-readable architecture and decisions in `docs/`; keep a compact
repository map in `llms.txt`.

## Setup and test commands

Use these exact commands unless the repository configuration changes:

```bash
python -m pip install -e ".[test]"
python -m pytest
hletterscriptgen version
hletterscriptgen schema --format json
hletterscriptgen validate examples/letter_set/writer_example.json --format json
```

- Python 3.11+ is required.
- No lint command is configured unless one is added explicitly.

## Architectural boundaries

- `hletterscriptgen` owns the **code** that turns rights-clean Hebrew page
  scans into per-writer letter-glyph image sets.
- `hletterscript` (separate repo) owns the **published letter-set datasets**.
  Do not commit generated glyph images to this repo.
- `public-domain-hand-written-hebrew-scans` (separate repo) owns
  **upstream scans** and their rights records.
- `hocrsyngen`, `hocrgen`, `HeOCR`, `HeOCRsynth` are downstream consumers.
  Do not import them from `hletterscriptgen` and do not build their
  governance, release, or composition surfaces here.

## Stable public surfaces

- CLI: `hletterscriptgen {version, schema, validate, generate, check-eligible}`.
- Output contract: `letter_set.v1` (see
  `src/hletterscriptgen/schemas/letter_set.schema.json` and
  `docs/letter_set_v1.md`).
- Example fixture: `examples/letter_set/writer_example.json` — used by CI to
  guard the contract. Treat changes to it as schema-level changes.

## Rights-carryover rules

- Every variant must carry a `source.scan_entry_id` that resolves against
  the upstream `public-domain-hand-written-hebrew-scans` index, plus a
  `source.license` matching the upstream record. The generator never
  invents, broadens, or relicenses upstream rights.
- `license_summary.licenses` must include every distinct license that
  appears in any variant of the set. Do not omit licenses just because they
  are minority members of the set.
- See [`LICENSE-POLICY.md`](LICENSE-POLICY.md).

## Documentation hygiene

- `AGENTS.md` — static rules only (this file).
- `llms.txt` — compact repository map only.
- `docs/` — human-readable architecture, contracts, plans, decisions.
- `README.md` — user-facing entry point, not a planning archive.

## Branch and PR conventions

- Branches: `feat/...`, `fix/...`, `docs/...`, `refactor/...`, `test/...`.
- Conventional commits: `type(scope): subject`.
- PR summaries should list files created/modified and tests run.
- Do not force-push `main`. Do not skip hooks (`--no-verify`).
