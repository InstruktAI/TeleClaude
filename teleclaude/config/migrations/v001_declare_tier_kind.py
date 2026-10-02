"""Declare the kind on registered tier documents."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 1
KINDS: Final = frozenset(
    {ConfigSubjectKind.GLOBAL, ConfigSubjectKind.PERSON, ConfigSubjectKind.COMPANY, ConfigSubjectKind.PROJECT}
)
READ_REQUIRES_REGISTRY: Final = False
_KIND = "kind"


def up(document: MutableMapping[str, object], subject: SubjectRef) -> None:
    """Add the registered tier only when the document has not declared one."""
    document.setdefault(_KIND, subject.kind.value)
