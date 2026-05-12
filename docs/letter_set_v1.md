# The `letter_set.v1` contract

`letter_set.v1` is the **stable public surface** that `hletterscriptgen`
emits. Each document describes one writer's letter-glyph collection.

The authoritative source is
[`src/hletterscriptgen/schemas/letter_set.schema.json`](../src/hletterscriptgen/schemas/letter_set.schema.json).
The example
[`examples/letter_set/writer_example.json`](../examples/letter_set/writer_example.json)
is exercised by CI and must remain valid.

## Top-level shape

```jsonc
{
  "schema_version": "letter_set.v1",
  "writer_id": "...",
  "writer_label": "...",                 // optional; must not carry PII
  "writer_provenance": { ... },          // required
  "generator": {
    "name": "hletterscriptgen",
    "version": "...",
    "config_hash": "<64-char lowercase sha256 hex>"
  },
  "generated_at": "2026-05-12T00:00:00Z",
  "upstream": {
    "repo": "HeOCR/public-domain-hand-written-hebrew-scans",
    "revision": "<git commit sha>"
  },
  "letters": {
    "א": [ { /* variant */ }, ... ],
    "ב": [ { /* variant */ } ],
    ...
  },
  "license_summary": { "licenses": ["PDM-1.0", "CC-BY-SA-4.0"], "notes": "..." }
}
```

## Field notes

### `writer_id`

Stable identifier for the writer. The authoritative namespace is the
**publishing repo**, i.e.
[`HeOCR/hletterscript`](https://github.com/HeOCR/hletterscript) — once
a letter set is published there, its `writer_id` must be globally
unique within that repo and must remain stable across regenerations so
downstream consumers can re-resolve a writer over time. Unpublished
generator runs may use any stable scheme.

### `writer_label`

Optional human-readable label. **Must not** carry PII (real names,
addresses, contact info, etc.). Use anonymized or collection-derived
labels only. If in doubt, omit.

### `writer_provenance`

**Required.** Records how the writer identity was established and which
upstream scan entries are attributed to them. `source_repo` is normally
`HeOCR/public-domain-hand-written-hebrew-scans`; `source_entry_ids` are
the upstream `entries.jsonl` ids. `attribution_method` is a short tag
(e.g. `collection_metadata`, `manual_review`, `fixture`).

The set of `source_entry_ids` must be a **superset** of every
`source.scan_entry_id` referenced under `letters` — this is enforced by
the cross-field validator in `hletterscriptgen.validation`, not by the
JSON Schema alone.

### `upstream`

**Required.** Pins the letter set to the exact upstream revision it was
generated from, so the run is reproducible and rights evidence is
anchored to a specific upstream state. `repo` is `owner/name` form;
`revision` is normally a git commit SHA.

### `generator.config_hash`

**Required.** Lowercase SHA-256 hex digest (exactly 64 characters)
computed as:

1. Resolve the full generator configuration into a single JSON value
   (the value the generator would actually read after defaults and
   overrides are applied).
2. Serialize that value to UTF-8 **canonical JSON**: object keys sorted
   lexicographically, no whitespace, no trailing newline, no
   non-ASCII escapes beyond what JSON requires.
3. Compute SHA-256 over those bytes and emit the digest in lowercase hex.

Two runs with the same resolved config must yield identical hashes;
two runs with any meaningful config difference must yield different
hashes.

The package ships a reference implementation:
``hletterscriptgen.config_hash(payload)``. Use it rather than hand-rolling
canonicalization in consumer code.

### `letters`

A mapping from a single Hebrew letter character (base or final form,
`U+05D0`–`U+05EA`) to an array of one or more **variants**.

- Multiple variants per letter are expected — different scans of the
  same writer often yield several instances of the same letter, which
  downstream consumers can sample over.
- Final forms (`ך`, `ם`, `ן`, `ף`, `ץ`) are treated as distinct keys
  from their base forms; this is intentional, because composition
  consumers need to render the right form in the right position.

### Variant entries

| Field | Notes |
| --- | --- |
| `variant_id` | Stable id within the set. |
| `asset_path` | POSIX path relative to the letter-set root. No leading `/` (schema-enforced); no `..` segment (cross-field-enforced). |
| `checksum_sha256` | Lowercase SHA-256 hex digest of the asset bytes. Real letter sets must use real checksums; the example fixture's all-zero/all-one digests are intentional placeholders. |
| `image.{width_px,height_px,format}` | Image metadata. `format` ∈ `png`, `webp`, `tiff`. |
| `source.scan_entry_id` | Upstream entry id (resolves in `public-domain-hand-written-hebrew-scans`). Cross-field validator checks it appears in `writer_provenance.source_entry_ids`. |
| `source.scan_url` | Optional URL pointer to the source scan. RFC 3986 URI; checked when format-checking is enabled. |
| `source.license` | One of the accepted SPDX / `LicenseRef-*` identifiers (see `$defs.license_id` in the schema). Extending the allow-list requires a schema change. |
| `source.rights_evidence` | Optional free-form note or URL with rights evidence. |
| `source.bbox_in_source` | **Required.** Pixel-space crop box on the source scan, so every variant is auditable against its source. |
| `extracted_at` | Optional ISO 8601 timestamp for the extraction. |
| `notes` | Optional free-form. |

### `license_summary`

Aggregate summary of distinct licenses present across variants.
Authoritative rights remain at the **variant** level in
`source.license`; consumers must not rely on `license_summary` alone
for filtering.

The cross-field validator enforces that `license_summary.licenses`
(as a set) **equals** the set of distinct `source.license` values
across all variants — no missing licenses, no extra licenses. A doc
that disagrees fails `hletterscriptgen validate`.

## Versioning

- v1 is additive within the `letter_set.v1` namespace. Additive fields
  on existing objects are allowed if they keep older valid documents
  valid.
- Breaking changes require a new version (`letter_set.v2`). The v1
  schema must remain available until downstream consumers migrate.
- CI re-validates the example fixture on every change. If the schema
  changes meaningfully, update both the schema and the fixture in the
  same PR.
