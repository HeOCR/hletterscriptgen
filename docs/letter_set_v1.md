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
  "writer_label": "...",                 // optional
  "writer_provenance": { ... },          // optional but recommended
  "generator": { "name": "hletterscriptgen", "version": "...", "config_hash": "..." },
  "generated_at": "2026-05-12T00:00:00Z",
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

Stable identifier scoped to this repository's view of the writer. Must
remain stable across regenerations so downstream consumers can
re-resolve a writer over time.

### `writer_provenance`

Records how the writer identity was established and which upstream scan
entries are attributed to them. `source_repo` is normally
`HeOCR/public-domain-hand-written-hebrew-scans`; `source_entry_ids` are
the upstream `entries.jsonl` ids.

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
| `asset_path` | POSIX path relative to the letter-set root. No `..`, no leading `/`. |
| `checksum_sha256` | SHA-256 hex digest of the asset bytes. |
| `image.{width_px,height_px,format}` | Image metadata. `format` ∈ `png`, `webp`, `tiff`. |
| `source.scan_entry_id` | Upstream entry id (resolves in `public-domain-hand-written-hebrew-scans`). |
| `source.scan_url` | Optional URL pointer to the source scan. |
| `source.license` | SPDX or `LicenseRef-*` identifier matching the upstream record. |
| `source.rights_evidence` | Optional free-form note or URL with rights evidence. |
| `source.bbox_in_source` | Pixel-space crop box on the source scan. |
| `extracted_at` | Optional ISO 8601 timestamp for the extraction. |
| `notes` | Optional free-form. |

### `license_summary`

Aggregate, convenience-only summary of distinct licenses present
across variants. Authoritative rights remain at the **variant** level
in `source.license`; consumers must not rely on `license_summary`
alone for filtering.

## Versioning

- v1 is additive within the `letter_set.v1` namespace. Additive fields
  on existing objects are allowed if they keep older valid documents
  valid.
- Breaking changes require a new version (`letter_set.v2`). The v1
  schema must remain available until downstream consumers migrate.
- CI re-validates the example fixture on every change. If the schema
  changes meaningfully, update both the schema and the fixture in the
  same PR.
