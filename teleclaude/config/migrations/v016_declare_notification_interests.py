"""Converge a person's document to carry notification interests."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 16
KINDS: Final = frozenset({ConfigSubjectKind.PERSON})
READ_REQUIRES_REGISTRY: Final = False
_NOTIFICATIONS = "notifications"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Add the interests key, empty, where the document has none; a present key stays as written.

    A person document carries no role, so no starting interests are derived here:
    they are written only when a person is created.
    """
    document.setdefault(_NOTIFICATIONS, {})
