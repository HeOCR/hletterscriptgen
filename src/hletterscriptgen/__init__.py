"""hletterscriptgen: per-writer Hebrew letter-glyph image set generator."""

from __future__ import annotations

__version__ = "0.1.0.dev0"
LETTER_SET_SCHEMA_ID = "letter_set.v1"

# Hebrew base + final letter forms, U+05D0..U+05EA.
HEBREW_LETTERS: frozenset[str] = frozenset(
    chr(codepoint) for codepoint in range(0x05D0, 0x05EB)
)

# Licenses accepted by the rights policy (mirrors letter_set.v1
# $defs.license_id). Extending this set is a schema change.
ALLOWED_LICENSES: frozenset[str] = frozenset(
    {
        "CC0-1.0",
        "PDM-1.0",
        "LicenseRef-Public-Domain-Israel",
        "LicenseRef-Public-Domain-Ukraine",
        "CC-BY-4.0",
        "CC-BY-3.0",
        "CC-BY-SA-4.0",
        "CC-BY-SA-3.0",
    }
)

__all__ = [
    "ALLOWED_LICENSES",
    "HEBREW_LETTERS",
    "LETTER_SET_SCHEMA_ID",
    "__version__",
]
