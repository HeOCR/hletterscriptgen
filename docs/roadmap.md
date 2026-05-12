# Roadmap

Staged milestones beyond the initial scaffolding. Items are intentionally
phrased as goals, not promises; sequencing may shift as upstream and
downstream needs become clearer.

## M0 — Scaffolding (this PR)

- Python package and CLI (`version`, `schema`, `validate`, placeholder
  `generate`).
- `letter_set.v1` JSON Schema + example fixture; cross-field validation
  for license-summary consistency and provenance integrity.
- pytest suite + CLI smoke; ruff + mypy-strict in CI.
- CI on Ubuntu/macOS, Python 3.11 / 3.12; SHA-pinned actions.
- Tag-triggered release workflow that builds, `twine check`s, and
  attaches sdist + wheel to a GitHub release.
- PyPI publishing is intentionally **deferred** until the org sets up
  PyPI trusted publishing; users install from GitHub release assets in
  the meantime.
- Governance: AGENTS, CONTRIBUTING, LICENSE, LICENSE-POLICY, SECURITY,
  CODEOWNERS.

## M1 — Upstream integration contract

- Concrete loader for upstream `entries.jsonl` records (read-only).
- Eligibility filter (CC0 / PDM / jurisdictional PD / CC-BY / CC-BY-SA).
- Pinning of the consumed upstream revision in run output, so
  regeneration is reproducible.

## M2 — Writer attribution

- Mechanism for grouping upstream entries by writer, with the chosen
  attribution method recorded in `writer_provenance.attribution_method`.
- Manual override path (config-driven), since collection metadata will
  not always disambiguate writers cleanly.

## M3 — Glyph extraction MVP

- First end-to-end extraction over a small, hand-picked writer
  attribution. Emits one or more `letter_set.v1` documents plus
  referenced assets.
- Deterministic outputs: same upstream revision + same config →
  bit-identical letter set tree.

## M4 — Variant quality and dedupe

- Per-variant quality metrics carried alongside `image` metadata.
- Deduplication of near-identical extractions within a writer's set.

## M5 — Publishing flow into `hletterscript`

- Reproducible packaging of a generated tree for commit into
  `hletterscript`. Includes checksums and a top-level manifest.

## M6 — Schema v1.1+ / v2 evolution

- Additive v1 evolutions as downstream consumers identify gaps.
- A v2 schema, if downstream needs justify a breaking change. v1 stays
  available until consumers migrate.
