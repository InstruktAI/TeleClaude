"""Mark the schema that may declare a project's GitHub todo repository."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 25
KINDS: Final = frozenset({ConfigSubjectKind.PROJECT})
READ_REQUIRES_REGISTRY: Final = False


def up(_document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Preserve repository declarations unchanged; absence already means none."""
