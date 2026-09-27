"""Declare the machine tier in the stored configuration document."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config.subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 6
KINDS: Final = frozenset({ConfigSubjectKind.COMPUTER})
READ_REQUIRES_REGISTRY: Final = False
_KIND = "kind"
_COMPUTER = "computer"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Insert a missing kind first while preserving round-trip comments and key order."""
    if _KIND in document:
        return
    insert = getattr(document, "insert", None)
    if callable(insert):
        insert(0, _KIND, _COMPUTER)
        return
    existing = tuple(document.items())
    document.clear()
    document[_KIND] = _COMPUTER
    document.update(existing)
