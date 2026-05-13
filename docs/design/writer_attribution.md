# Writer attribution — config contract (M2)

> **Status: Implemented.** The concrete config format and loader live in
> `src/hletterscriptgen/attribution.py`. Tests are in
> `tests/test_attribution.py`; the canonical fixture is
> `tests/fixtures/attribution/writer_profile.json`.

## Goal

Provide a human-curated mechanism for grouping upstream `entries.jsonl`
records by writer, with the attribution method carried into the output
as `writer_provenance.attribution_method`. Auto-clustering is
intentionally out of scope.

## Writer profile — config file

The config is a single JSON file called a **writer profile**. It names
the local upstream checkout and declares one or more writer blocks.

```json
{
  "upstream_path": "../public-domain-hand-written-hebrew-scans",
  "writers": [
    {
      "writer_id": "writer_bialik",
      "attribution_method": "collection_metadata",
      "entry_ids": [
        "commons__bialik_letter_safed_1927__p0001",
        "commons__bialik_letter_safed_1927__p0002"
      ],
      "notes": "Attributed via Wikimedia Commons collection metadata"
    },
    {
      "writer_id": "writer_herzl",
      "attribution_method": "manual_review",
      "entry_ids": [
        "commons__herzl_diary_1897__p0001"
      ]
    }
  ]
}
```

### Field reference

| Field | Type | Required | Notes |
|---|---|---|---|
| `upstream_path` | string | yes | Path to the local upstream checkout (relative or absolute). Stored in the profile so the whole file is a hashable artifact. |
| `writers` | array | yes | Ordered list of writer blocks. |
| `writer_id` | string | yes | Stable, machine-readable identifier. Must be unique within the file. |
| `attribution_method` | string (enum) | yes | How writer identity was established. See below. |
| `entry_ids` | array of strings | yes | Non-empty list of upstream `entry_id` values attributed to this writer. Each id may appear under at most one writer. |
| `notes` | string | no | Free-text annotation for human reviewers. |

### Attribution methods

| Value | Meaning |
|---|---|
| `collection_metadata` | The upstream collection's own metadata (e.g. Wikimedia Commons `creator` field) names the writer. |
| `manual_review` | A human reviewer examined the scan(s) and attributed them to the writer. |

## Validation rules

`load_attribution(path)` enforces all of the following; violations raise
typed subclasses of `AttributionLoadError`:

1. The file is valid JSON and a top-level object.
2. `upstream_path` is present and a string.
3. `writers` is present and a list.
4. Each writer entry is a JSON object with a string `writer_id`.
5. `attribution_method` is a string and a member of `AttributionMethod`.
6. `entry_ids` is a non-empty list.
7. `writer_id` values are unique across the file.
8. Each `entry_id` appears under at most one writer.

`validate_attribution_against_entries(attributions, entries, *, path)` cross-checks
the attributed entry_ids against a live upstream entry stream and raises
`AttributionEntryMismatchError` (carrying the full set of unknown ids)
if any id is not found. The check is strict — unknown ids are almost
always typos or stale references.

## Design decisions

**Why JSON, not YAML?** No new dependency; the file is machine-readable
and diff-friendly. Writer profiles are small enough that YAML's
multi-line convenience is not needed.

**Why `upstream_path` in the config, not a call-time argument?** The
profile is a self-contained, hashable artifact that can be reproduced
without additional context. The path is part of the run configuration
and belongs alongside the writer assignments.

**Why `StrEnum` for `AttributionMethod`?** Strict typing catches unknown
strings at load time rather than silently propagating them downstream.
Adding a new method requires a code change, which is intentional: methods
should be documented and reviewed, not invented ad-hoc in config files.

**Why raise on unknown entry_ids?** The config is hand-curated. A
reference to a non-existent entry_id is almost always a typo or a stale
copy-paste. Silent warnings would allow bad configs to propagate into the
extraction pipeline. Callers who need a softer policy can catch
`AttributionEntryMismatchError` and handle it themselves.

## Relationship to letter_extraction.md step 1

This document is the concrete implementation of step 1 ("Configuration")
in [`letter_extraction.md`](letter_extraction.md). The open question
"How is writer identity established when upstream metadata is silent?"
is answered here: **explicit config**. The generator does not
auto-cluster; that remains out of scope through at least M3.
