# Security and rights-issue reporting

`hletterscriptgen` generates outputs that propagate rights from
third-party scans. We treat both classic security vulnerabilities and
**rights-attribution defects** as serious; both should be reported
before any public discussion.

## Reporting

### Security vulnerabilities

If you believe you've found a vulnerability in the generator code,
CLI, or schema validator, please use GitHub's private vulnerability
reporting:

- Go to https://github.com/HeOCR/hletterscriptgen/security/advisories/new
- Describe the issue, steps to reproduce, and any suggested remediation.

Do **not** open a public issue or PR with exploit details.

### Rights-attribution defects

If you believe a letter set produced by this generator (in
`HeOCR/hletterscript` or anywhere else) misattributes rights — for
example, lists a license that does not actually apply to the upstream
scan, or references a writer the upstream record does not support —
please report it. Two paths, in preference order:

1. Open a private vulnerability advisory in this repo (link above) if
   you would prefer to discuss before going public.
2. Open a public issue in `HeOCR/hletterscriptgen` tagged
   `rights-attribution` if the situation does not benefit from
   privacy.

For takedown of an upstream scan, report directly in
[`HeOCR/public-domain-hand-written-hebrew-scans`](https://github.com/HeOCR/public-domain-hand-written-hebrew-scans);
once an upstream scan is removed or relicensed, regenerated letter
sets must drop or update the affected variants.

## Supported versions

The repository follows semantic versioning. Security fixes target the
latest minor release line. Older release lines are best-effort; if you
depend on one and need backporting, mention it in the report.

## Scope

In scope:

- The generator code, CLI, validation, and JSON Schema in this repo.
- Logic that produces or validates `letter_set.v1` documents.

Out of scope here (report to the relevant upstream / downstream repo):

- Rights records on upstream scans — `HeOCR/public-domain-hand-written-hebrew-scans`.
- Published letter-set datasets — `HeOCR/hletterscript`.
- Composed synthetic pages — `HeOCR/hocrsyngen`.
- Release-level governance — `HeOCR/hocrgen`.
