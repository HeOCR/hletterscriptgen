"""Writer attribution config: group upstream entries by writer.

A human curates a JSON "writer profile" that maps upstream ``entry_id``
values to writer identities. This module loads and validates that config
and cross-checks it against a live upstream entry stream.

The module exposes:

* :class:`AttributionMethod` — enum of recognised attribution methods.
* :class:`WriterAttribution` — typed record for a single writer's config.
* :class:`WriterProfile` — the top-level config object (upstream path +
  writers tuple + the path the profile was loaded from).
* :func:`load_attribution` — read and validate a writer-profile JSON file.
* :func:`validate_attribution_against_entries` — cross-check entry_ids
  against a live upstream entry stream; raises on unknown ids.

Attribution is explicitly hand-curated. The module never auto-clusters
or infers writer identity — that is intentionally out of scope.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from hletterscriptgen.upstream import UpstreamEntry


class AttributionMethod(StrEnum):
    """Recognised methods for establishing writer identity."""

    collection_metadata = "collection_metadata"
    manual_review = "manual_review"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AttributionLoadError(ValueError):
    """Base for all writer-profile load failures.

    ``path`` refers to the writer-profile JSON file that triggered the error.
    """

    def __init__(self, message: str, *, path: Path) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path


class DuplicateWriterIdError(AttributionLoadError):
    """Raised when the same ``writer_id`` appears more than once."""

    def __init__(self, writer_id: str, *, path: Path) -> None:
        super().__init__(f"duplicate writer_id {writer_id!r}", path=path)
        self.writer_id = writer_id


class DuplicateEntryIdError(AttributionLoadError):
    """Raised when an ``entry_id`` is claimed by two different writers."""

    def __init__(
        self,
        entry_id: str,
        first_writer: str,
        second_writer: str,
        *,
        path: Path,
    ) -> None:
        super().__init__(
            f"entry_id {entry_id!r} appears under both {first_writer!r} and"
            f" {second_writer!r}",
            path=path,
        )
        self.entry_id = entry_id
        self.first_writer = first_writer
        self.second_writer = second_writer


class EmptyEntryIdsError(AttributionLoadError):
    """Raised when a writer's ``entry_ids`` list is empty."""

    def __init__(self, writer_id: str, *, path: Path) -> None:
        super().__init__(f"writer {writer_id!r} has no entry_ids", path=path)
        self.writer_id = writer_id


class UnknownAttributionMethodError(AttributionLoadError):
    """Raised when ``attribution_method`` is not a member of :class:`AttributionMethod`."""

    def __init__(self, writer_id: str, value: str, *, path: Path) -> None:
        valid = ", ".join(m.value for m in AttributionMethod)
        super().__init__(
            f"writer {writer_id!r}: unknown attribution_method {value!r};"
            f" valid values: {valid}",
            path=path,
        )
        self.writer_id = writer_id
        self.value = value


class AttributionEntryMismatchError(AttributionLoadError):
    """Raised when attributed entry_ids are absent from the upstream entry stream."""

    def __init__(self, unknown_ids: frozenset[str], *, path: Path) -> None:
        ids_str = ", ".join(sorted(unknown_ids))
        super().__init__(
            f"entry_ids not found in upstream entries: {ids_str}",
            path=path,
        )
        self.unknown_ids = unknown_ids


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WriterAttribution:
    """Attribution record for a single writer."""

    writer_id: str
    attribution_method: AttributionMethod
    entry_ids: frozenset[str]
    notes: str | None = None


@dataclass(frozen=True)
class WriterProfile:
    """Top-level writer-profile config loaded from a JSON file."""

    upstream_path: Path
    writers: tuple[WriterAttribution, ...]
    source_path: Path


# ---------------------------------------------------------------------------
# Internal parsing helpers
# ---------------------------------------------------------------------------


def _parse_writer(raw: dict[str, Any], *, path: Path) -> WriterAttribution:
    try:
        writer_id: str = raw["writer_id"]
    except KeyError as exc:
        raise AttributionLoadError(
            "writer entry is missing required field 'writer_id'", path=path
        ) from exc

    raw_method = raw.get("attribution_method")
    if not isinstance(raw_method, str):
        raise AttributionLoadError(
            f"writer {writer_id!r}: 'attribution_method' must be a string",
            path=path,
        )
    try:
        method = AttributionMethod(raw_method)
    except ValueError as exc:
        raise UnknownAttributionMethodError(writer_id, raw_method, path=path) from exc

    raw_ids = raw.get("entry_ids", [])
    if not isinstance(raw_ids, list) or not raw_ids:
        raise EmptyEntryIdsError(writer_id, path=path)

    return WriterAttribution(
        writer_id=writer_id,
        attribution_method=method,
        entry_ids=frozenset(raw_ids),
        notes=raw.get("notes"),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_attribution(path: Path) -> WriterProfile:
    """Read and validate a writer-profile JSON file.

    Returns a :class:`WriterProfile` on success.

    Raises :class:`AttributionLoadError` (or a subclass) when:

    * the file is not valid JSON or is not a top-level object,
    * ``upstream_path`` is missing or not a string,
    * ``writers`` is missing or not a list,
    * any writer entry is malformed (missing ``writer_id``, bad
      ``attribution_method``, empty ``entry_ids``),
    * the same ``writer_id`` appears more than once, or
    * the same ``entry_id`` appears under two different writers.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AttributionLoadError(str(exc), path=path) from exc

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AttributionLoadError(f"invalid JSON: {exc.msg}", path=path) from exc

    if not isinstance(payload, dict):
        raise AttributionLoadError("expected a JSON object at top level", path=path)

    raw_upstream = payload.get("upstream_path")
    if not isinstance(raw_upstream, str):
        raise AttributionLoadError(
            "missing or non-string 'upstream_path'", path=path
        )

    raw_writers = payload.get("writers")
    if not isinstance(raw_writers, list):
        raise AttributionLoadError("'writers' must be a list", path=path)

    writers: list[WriterAttribution] = []
    seen_writer_ids: set[str] = set()
    seen_entry_ids: dict[str, str] = {}  # entry_id -> writer_id

    for raw_writer in raw_writers:
        if not isinstance(raw_writer, dict):
            raise AttributionLoadError(
                "each writer entry must be a JSON object", path=path
            )
        wa = _parse_writer(raw_writer, path=path)

        if wa.writer_id in seen_writer_ids:
            raise DuplicateWriterIdError(wa.writer_id, path=path)
        seen_writer_ids.add(wa.writer_id)

        for eid in wa.entry_ids:
            if eid in seen_entry_ids:
                raise DuplicateEntryIdError(
                    eid, seen_entry_ids[eid], wa.writer_id, path=path
                )
            seen_entry_ids[eid] = wa.writer_id

        writers.append(wa)

    return WriterProfile(
        upstream_path=Path(raw_upstream),
        writers=tuple(writers),
        source_path=path,
    )


def validate_attribution_against_entries(
    profile: WriterProfile,
    entries: Iterable[UpstreamEntry],
) -> None:
    """Raise if any attributed entry_id is absent from ``entries``.

    Cross-checks every ``entry_id`` declared across all writers in
    ``profile`` against the provided upstream entries. Raises
    :class:`AttributionEntryMismatchError` (carrying the full set of
    unknown ids) if any id is not found.

    Consuming the ``entries`` iterable is the caller's responsibility —
    pass an in-memory list when re-use is needed.
    """
    known_ids: frozenset[str] = frozenset(e.entry_id for e in entries)
    attributed_ids: frozenset[str] = frozenset(
        eid for wa in profile.writers for eid in wa.entry_ids
    )
    unknown = attributed_ids - known_ids
    if unknown:
        raise AttributionEntryMismatchError(unknown, path=profile.source_path)


__all__ = [
    "AttributionEntryMismatchError",
    "AttributionLoadError",
    "AttributionMethod",
    "DuplicateEntryIdError",
    "DuplicateWriterIdError",
    "EmptyEntryIdsError",
    "UnknownAttributionMethodError",
    "WriterAttribution",
    "WriterProfile",
    "load_attribution",
    "validate_attribution_against_entries",
]
