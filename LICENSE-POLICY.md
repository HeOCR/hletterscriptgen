# Licensing Policy

`hletterscriptgen` distinguishes between **code** (this repository) and the
**letter-set datasets** it produces (published to
[`HeOCR/hletterscript`](https://github.com/HeOCR/hletterscript)). Different
rules apply to each layer.

## 1. Repository code, schemas, and examples

- All source code, JSON Schemas, configuration, tests, and example fixtures
  shipped in this repository are licensed under the **MIT License** (see
  [`LICENSE`](LICENSE)).
- The example fixtures under `examples/` describe synthetic data; they do
  **not** carry, imply, or relicense rights from any upstream scan.

## 2. Generated letter-set datasets

The generator processes scans from
[`HeOCR/public-domain-hand-written-hebrew-scans`](https://github.com/HeOCR/public-domain-hand-written-hebrew-scans).
That upstream repository uses a compound licensing model with rights recorded
**per scan**. `hletterscriptgen` follows the same posture:

- Eligible upstream sources are limited to **Public Domain** (CC0, PDM, or
  jurisdictional public-domain dedications) and **CC-BY / CC-BY-SA**.
- Each emitted `letter_set.v1` document records the **per-variant** source
  license in `letters.<letter>[].source.license`. This is the authoritative
  rights record for each glyph image.
- `letter_set.v1.license_summary.licenses` is the **aggregated** set of
  distinct licenses appearing in the set. It is a convenience surface, not a
  substitute for per-variant evidence.
- The generator **does not relicense** glyphs. A glyph drawn from a CC-BY-SA
  scan remains CC-BY-SA when published in `hletterscript`; downstream
  consumers must honor attribution and ShareAlike requirements.

## 3. Downstream consumers

- `hocrsyngen` and any other downstream consumer must read per-variant
  licenses before composing aggregate outputs, and must apply the strictest
  applicable terms (e.g., ShareAlike propagates).
- Aggregated dataset releases (e.g., `HeOCR`, `HeOCRsynth`) are expected to
  filter or partition by license compatibility according to their own
  release-profile policies. That filtering is **not** performed here.

## 4. Rights evidence carryover

- `letters.<letter>[].source.scan_entry_id` must reference an entry in the
  upstream scan index so rights evidence remains traceable.
- `letters.<letter>[].source.rights_evidence` may carry a free-form note or
  URL inherited from the upstream record.

## 5. Takedown and removal

- Removal requests for upstream scans must be honored upstream first.
- Letter sets that reference a removed scan must be regenerated or have the
  affected variants excised. The generator must support deterministic
  regeneration so a removed source can be re-run against the current upstream
  state without disturbing unrelated variants.
