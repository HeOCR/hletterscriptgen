"""Canonical hashing helpers for letter_set.v1 fields."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(payload: Any) -> bytes:
    """Serialize ``payload`` to canonical JSON bytes.

    Canonical form: object keys sorted lexicographically, no whitespace
    between elements, no trailing newline. Non-ASCII characters are
    preserved (UTF-8 encoded) rather than escaped.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def config_hash(config: Any) -> str:
    """Compute the ``letter_set.v1`` ``generator.config_hash`` for a config.

    Returns the lowercase SHA-256 hex digest (64 chars) of the
    canonical-JSON serialization of ``config``. See
    ``docs/letter_set_v1.md`` for the algorithm.
    """
    return hashlib.sha256(canonical_json(config)).hexdigest()
