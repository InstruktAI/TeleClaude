"""Retire the top-level `channel_subscriptions` key from project documents."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 20
KINDS: Final = frozenset({ConfigSubjectKind.PROJECT})
READ_REQUIRES_REGISTRY: Final = False
_CHANNEL_SUBSCRIPTIONS = "channel_subscriptions"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Drop `channel_subscriptions`; the value is dropped, not moved, because nothing consumes it."""
    document.pop(_CHANNEL_SUBSCRIPTIONS, None)
