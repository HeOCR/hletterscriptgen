## Summary

<!-- One or two sentences describing the change. -->

## Files changed

<!-- Bulleted list of created/modified files (or "see diff"). -->

## Tests run

<!-- e.g. `python -m pytest`, `hletterscriptgen validate examples/letter_set/writer_example.json`. -->

## Scope check

- [ ] Change stays inside `hletterscriptgen` scope (code/schemas/validation),
      not `hletterscript` (data), upstream scans, or downstream consumers.
- [ ] If the `letter_set.v1` schema changed, `docs/letter_set_v1.md` and
      the example fixture are updated.
- [ ] Per-variant rights carryover (`source.license`) and aggregate
      `license_summary` semantics remain truthful.
