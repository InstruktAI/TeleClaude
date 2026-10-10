"""Declare the canonical-main activation trigger for project maintenance bindings."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 21
KINDS: Final = frozenset({ConfigSubjectKind.PROJECT})
READ_REQUIRES_REGISTRY: Final = False


def up(_document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Change nothing; the new optional trigger is absent from existing documents."""
