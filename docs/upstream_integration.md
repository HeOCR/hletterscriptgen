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

## How this repo consumes it

The loader lives in [`hletterscriptgen.upstream`](../src/hletterscriptgen/upstream.py).
It is read-only and operates on a local checkout — this repo never
fetches scans on its own.

1. **Pin an upstream revision.**
   [`upstream_pin_from_checkout(path)`](../src/hletterscriptgen/upstream.py)
   returns `(repo, revision)` for the
   [`letter_set.v1.upstream`](letter_set_v1.md#upstream) block. `repo`
   is the `owner/name` form derived from `git remote get-url origin`
   (https, ssh, and `.git`-suffixed URLs all normalize the same way);
   `revision` is `git rev-parse HEAD`. It raises
   `UpstreamCheckoutDirtyError` when `git status --porcelain` is
   non-empty — a dirty pin would silently misrepresent the bytes the
   generator read.
2. **Stream entries.**
   [`load_entries(path)`](../src/hletterscriptgen/upstream.py) yields
   `UpstreamEntry` records from a local `entries.jsonl`. Blank lines
   are tolerated; a malformed JSON line raises `UpstreamLoadError`
   carrying the 1-based `line_number`. `UpstreamEntry` is a typed,
   frozen subset of the upstream `entry.schema.json` (`entry_id`,
   `source_id`, `creators[]`, `files[]`, `rights`, `quality`) — the
   parts the generator pipeline actually consumes.
3. **Filter by rights and quality.**
   [`is_eligible(entry)`](../src/hletterscriptgen/upstream.py) enforces
   [`LICENSE-POLICY.md`](../LICENSE-POLICY.md):
   - `rights.license_expression` ∈ `ALLOWED_LICENSES` (CC0 / PDM /
     jurisdictional PD / CC-BY / CC-BY-SA).
   - `rights.commercial_use_allowed`, `rights.derivatives_allowed`,
     and `rights.scan_redistribution_allowed` are all `True`. `None`
     fails the gate intentionally — only positive assertions pass.
   - `rights.verification_status ∉ FORBIDDEN_VERIFICATION_STATUSES`
     (`unverified`, `source_note_only`, `conflicting`, `rejected`).
     Only `primary_page_checked` is a positive verification.
   - `quality.usable_for_htr` is `True`.

   The sibling helper
   [`explain_ineligible(entry)`](../src/hletterscriptgen/upstream.py)
   returns the list of human-readable failure reasons (empty when
   eligible). Future CLI output will render those reasons.
4. **Group by writer.** (Planned, M2.) Writer identity is established
   from upstream collection metadata or explicit attribution and is
   recorded under `writer_provenance.attribution_method` so it can be
   audited.
5. **Extract per-letter variants.** (Planned, M3.) Glyphs are segmented
   from the selected scans and emitted as `variant` entries on the
   appropriate Hebrew-letter key.
6. **Carry rights through.** Each variant's `source.license` is copied
   from the upstream entry's `rights.license_expression`. The generator
   does not rewrite, broaden, or relicense rights.

## Non-goals

- This repo does **not** crawl, scrape, or fetch new scans.
- This repo does **not** edit or extend the upstream index.
- This repo does **not** make rights determinations; if an upstream
  record is wrong, the fix lands upstream and we regenerate.
