"""Upstream integration: read and filter ``public-domain-hand-written-hebrew-scans``.

This module is read-only: it consumes a local checkout of the upstream
scan corpus (``HeOCR/public-domain-hand-written-hebrew-scans``) and
exposes the records the generator pipeline actually needs. The full
upstream contract is broader than what is modelled here; see
``schemas/entry.schema.json`` in the upstream repo.

The module exposes:

* :class:`UpstreamEntry` (and nested :class:`UpstreamCreator`,
  :class:`UpstreamFile`, :class:`UpstreamRights`, :class:`UpstreamQuality`)
  — a typed, frozen subset of a per-scan entry.
* :func:`load_entries` — stream a local ``entries.jsonl``.
* :func:`is_eligible` / :func:`explain_ineligible` — enforce the
  rights-and-quality gate declared in ``LICENSE-POLICY.md``.
* :func:`upstream_pin_from_checkout` — derive the ``(repo, revision)``
  pin recorded in ``letter_set.v1.upstream`` from a clean checkout.

The eligibility gate is intentionally strict — entries pass only when
the upstream record positively asserts each required property. ``None``
values (which upstream uses for "not known") never satisfy the gate.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hletterscriptgen import ALLOWED_LICENSES

# Upstream ``rights.verification_status`` values that disqualify an
# entry. The upstream enum is
# ``{unverified, source_note_only, primary_page_checked, conflicting, rejected}``;
# only ``primary_page_checked`` represents a positive verification, so
# every other state is rejected here.
FORBIDDEN_VERIFICATION_STATUSES: frozenset[str] = frozenset(
    {"unverified", "source_note_only", "conflicting", "rejected"}
)


class UpstreamLoadError(ValueError):
    """Raised when an ``entries.jsonl`` line cannot be parsed.

    ``line_number`` is 1-based and refers to the offending line in the
    source file.
    """

    def __init__(self, message: str, *, path: Path, line_number: int) -> None:
        super().__init__(f"{path}:{line_number}: {message}")
        self.path = path
        self.line_number = line_number


class UpstreamCheckoutDirtyError(RuntimeError):
    """Raised when an upstream checkout has uncommitted changes.

    Reproducibility requires the pinned revision to fully describe the
    bytes the generator read.
    """


class UpstreamDetachedHeadError(RuntimeError):
    """Raised when an upstream checkout is in detached HEAD state.

    A detached HEAD commit may exist only locally, making the pinned
    revision unreachable for anyone reproducing the run from the remote.
    Check out a branch or tag before pinning.
    """


@dataclass(frozen=True)
class UpstreamCreator:
    name: str
    role: str
    death_year: int | None
    authority_url: str | None = None


@dataclass(frozen=True)
class UpstreamFile:
    local_path: str | None
    sha256: str | None
    mime_type: str | None
    width_px: int | None
    height_px: int | None


@dataclass(frozen=True)
class UpstreamRights:
    license_expression: str | None
    commercial_use_allowed: bool | None
    derivatives_allowed: bool | None
    scan_redistribution_allowed: bool | None
    verification_status: str


@dataclass(frozen=True)
class UpstreamQuality:
    usable_for_htr: bool | None
    legibility: str


@dataclass(frozen=True)
class UpstreamEntry:
    entry_id: str
    source_id: str
    creators: tuple[UpstreamCreator, ...]
    files: tuple[UpstreamFile, ...]
    rights: UpstreamRights
    quality: UpstreamQuality


def _parse_creator(raw: dict[str, Any]) -> UpstreamCreator:
    return UpstreamCreator(
        name=raw["name"],
        role=raw["role"],
        death_year=raw.get("death_year"),
        authority_url=raw.get("authority_url"),
    )


def _parse_file(raw: dict[str, Any]) -> UpstreamFile:
    return UpstreamFile(
        local_path=raw.get("local_path"),
        sha256=raw.get("sha256"),
        mime_type=raw.get("mime_type"),
        width_px=raw.get("width_px"),
        height_px=raw.get("height_px"),
    )


def _parse_rights(raw: dict[str, Any]) -> UpstreamRights:
    return UpstreamRights(
        license_expression=raw.get("license_expression"),
        commercial_use_allowed=raw.get("commercial_use_allowed"),
        derivatives_allowed=raw.get("derivatives_allowed"),
        scan_redistribution_allowed=raw.get("scan_redistribution_allowed"),
        verification_status=raw["verification_status"],
    )


def _parse_quality(raw: dict[str, Any]) -> UpstreamQuality:
    return UpstreamQuality(
        usable_for_htr=raw.get("usable_for_htr"),
        legibility=raw["legibility"],
    )


def _parse_entry(raw: dict[str, Any]) -> UpstreamEntry:
    return UpstreamEntry(
        entry_id=raw["entry_id"],
        source_id=raw["source_id"],
        creators=tuple(_parse_creator(c) for c in raw.get("creators", [])),
        files=tuple(_parse_file(f) for f in raw.get("files", [])),
        rights=_parse_rights(raw["rights"]),
        quality=_parse_quality(raw["quality"]),
    )


def load_entries(path: Path) -> Iterator[UpstreamEntry]:
    """Stream :class:`UpstreamEntry` records from ``entries.jsonl``.

    Blank lines (whitespace-only) are skipped. A line that is not valid
    JSON, or whose shape does not match the modelled subset, raises
    :class:`UpstreamLoadError` carrying the 1-based ``line_number``.
    """
    with path.open("r", encoding="utf-8") as fh:
        for line_number, raw_line in enumerate(fh, start=1):
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise UpstreamLoadError(
                    f"invalid JSON: {exc.msg}",
                    path=path,
                    line_number=line_number,
                ) from exc
            if not isinstance(payload, dict):
                raise UpstreamLoadError(
                    "expected a JSON object",
                    path=path,
                    line_number=line_number,
                )
            try:
                yield _parse_entry(payload)
            except (KeyError, TypeError) as exc:
                raise UpstreamLoadError(
                    f"missing or malformed field: {exc}",
                    path=path,
                    line_number=line_number,
                ) from exc


def explain_ineligible(entry: UpstreamEntry) -> list[str]:
    """Return human-readable reasons ``entry`` fails eligibility.

    Returns an empty list when the entry passes. The check mirrors
    :func:`is_eligible`; the two stay in lockstep.
    """
    reasons: list[str] = []
    rights = entry.rights
    if rights.license_expression not in ALLOWED_LICENSES:
        reasons.append(
            f"rights.license_expression {rights.license_expression!r} "
            "is not in the eligible license set"
        )
    if rights.commercial_use_allowed is not True:
        reasons.append("rights.commercial_use_allowed is not True")
    if rights.derivatives_allowed is not True:
        reasons.append("rights.derivatives_allowed is not True")
    if rights.scan_redistribution_allowed is not True:
        reasons.append("rights.scan_redistribution_allowed is not True")
    if rights.verification_status in FORBIDDEN_VERIFICATION_STATUSES:
        reasons.append(
            f"rights.verification_status {rights.verification_status!r} is forbidden"
        )
    if entry.quality.usable_for_htr is not True:
        reasons.append("quality.usable_for_htr is not True")
    return reasons


def is_eligible(entry: UpstreamEntry) -> bool:
    """Whether ``entry`` satisfies the LICENSE-POLICY rights-and-quality gate."""
    return not explain_ineligible(entry)


# Match the trailing ``owner/name`` of an ``origin`` URL. Handles
# ``https://host/owner/name(.git)``, ``git@host:owner/name(.git)``,
# ``ssh://git@host/owner/name(.git)``, and ``git://`` variants.
_REMOTE_TAIL_RE = re.compile(r"[:/]([^:/\s]+)/([^:/\s]+?)(?:\.git)?/?$")


def _normalize_remote_url(url: str) -> str:
    match = _REMOTE_TAIL_RE.search(url.strip())
    if not match:
        raise ValueError(f"could not parse 'owner/name' from remote URL: {url!r}")
    return f"{match.group(1)}/{match.group(2)}"


def _run_git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {path}: {result.stderr.strip()}"
        )
    return result.stdout


def upstream_pin_from_checkout(path: Path) -> tuple[str, str]:
    """Return ``(repo, revision)`` suitable for ``letter_set.v1.upstream``.

    * ``repo`` is the ``owner/name`` form derived from
      ``git remote get-url origin``.
    * ``revision`` is the current ``HEAD`` SHA.

    Raises :class:`UpstreamCheckoutDirtyError` when the working tree is
    dirty, and :class:`UpstreamDetachedHeadError` when HEAD is detached.
    Both conditions risk pinning a revision that is unreachable on the
    remote, breaking reproducibility for anyone re-running from the same
    upstream spec.
    """
    porcelain = _run_git(path, "status", "--porcelain")
    if porcelain.strip():
        raise UpstreamCheckoutDirtyError(
            f"upstream checkout at {path} has uncommitted changes; "
            "commit, stash, or reset before pinning"
        )
    # ``git symbolic-ref`` exits non-zero when HEAD is detached.
    sym_result = subprocess.run(
        ["git", "-C", str(path), "symbolic-ref", "--quiet", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if sym_result.returncode != 0:
        raise UpstreamDetachedHeadError(
            f"upstream checkout at {path} is in detached HEAD state; "
            "check out a branch or tag before pinning"
        )
    remote_url = _run_git(path, "remote", "get-url", "origin").strip()
    revision = _run_git(path, "rev-parse", "HEAD").strip()
    return _normalize_remote_url(remote_url), revision


__all__ = [
    "FORBIDDEN_VERIFICATION_STATUSES",
    "UpstreamCheckoutDirtyError",
    "UpstreamCreator",
    "UpstreamDetachedHeadError",
    "UpstreamEntry",
    "UpstreamFile",
    "UpstreamLoadError",
    "UpstreamQuality",
    "UpstreamRights",
    "explain_ineligible",
    "is_eligible",
    "load_entries",
    "upstream_pin_from_checkout",
]
