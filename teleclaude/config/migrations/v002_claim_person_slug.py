"""Declare a person's registry slug in the person's document."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 2
KINDS: Final = frozenset({ConfigSubjectKind.PERSON})
READ_REQUIRES_REGISTRY: Final = False
_SLUG = "slug"


def up(document: MutableMapping[str, object], subject: SubjectRef) -> None:
    """Add the registry slug when the document does not already carry one."""
    if subject.instance is not None:
        document.setdefault(_SLUG, subject.instance)
