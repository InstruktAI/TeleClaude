"""Grandfather effective capabilities on registered projects before the default flips."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config.subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 8
KINDS: Final = frozenset({ConfigSubjectKind.PROJECT})
READ_REQUIRES_REGISTRY: Final = True
_CAPABILITIES: Final = ("code", "docs", "agents")
_ENABLED = "enabled"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Materialize enabled defaults for registered projects that omitted a block."""
    for capability in _CAPABILITIES:
        value = document.get(capability)
        if capability not in document:
            document[capability] = {_ENABLED: True}
        elif isinstance(value, MutableMapping) and _ENABLED not in value:
            value[_ENABLED] = True
