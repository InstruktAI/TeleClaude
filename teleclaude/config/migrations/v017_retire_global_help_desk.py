"""Retire the platform help desk's declaration from the global document."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 17
KINDS: Final = frozenset({ConfigSubjectKind.GLOBAL})
READ_REQUIRES_REGISTRY: Final = False
_HELP_DESK = "help_desk"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Drop `help_desk`; its value is dropped, not moved, because no platform desk remains to declare."""
    document.pop(_HELP_DESK, None)
