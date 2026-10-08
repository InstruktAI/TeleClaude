"""Retire the event-domain block from the global document."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 15
KINDS: Final = frozenset({ConfigSubjectKind.GLOBAL})
READ_REQUIRES_REGISTRY: Final = False
_EVENT_DOMAINS = "event_domains"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Drop `event_domains`; its value is dropped, not moved, because nothing consumes it."""
    document.pop(_EVENT_DOMAINS, None)
