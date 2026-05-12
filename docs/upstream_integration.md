# Upstream integration

`hletterscriptgen` consumes scans from
[`HeOCR/public-domain-hand-written-hebrew-scans`](https://github.com/HeOCR/public-domain-hand-written-hebrew-scans).
That upstream repo holds the authoritative rights records; this repo
defers to them.

## Upstream contract

- `data/index/sources.jsonl` — institution / collection / item / source-lead
  records (one JSON object per line).
- `data/index/entries.jsonl` — per-scan records (one JSON object per scan)
  with per-scan rights, checksums, and provenance.
- `schemas/source.schema.json` and `schemas/entry.schema.json` — the
  upstream contracts that those JSONL files conform to.

The upstream repo uses a compound licensing model: repository-authored
metadata is CC0, while per-scan rights are recorded individually. See
`LICENSE.md` in the upstream repo.

## How this repo will consume it

1. **Pin an upstream revision.** Each generator run will declare the
   exact upstream commit it read from, so re-runs are reproducible and
   rights evidence is anchored to a specific upstream state.
2. **Filter by rights.** Only entries whose recorded license is on this
   project's eligibility list (CC0 / PDM / jurisdictional PD / CC-BY /
   CC-BY-SA) participate.
3. **Group by writer.** Writer identity is established from upstream
   collection metadata or explicit attribution; it is recorded under
   `writer_provenance.attribution_method` so it can be audited.
4. **Extract per-letter variants.** Glyphs are segmented from the
   selected scans and emitted as `variant` entries on the appropriate
   Hebrew-letter key.
5. **Carry rights through.** Each variant's `source.license` is copied
   from the upstream entry's recorded license. The generator does not
   rewrite, broaden, or relicense rights.

## Non-goals

- This repo does **not** crawl, scrape, or fetch new scans.
- This repo does **not** edit or extend the upstream index.
- This repo does **not** make rights determinations; if an upstream
  record is wrong, the fix lands upstream and we regenerate.
