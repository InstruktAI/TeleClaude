"""Retire the break-glass alert fields from the machine document's `telegram` section."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 22
KINDS: Final = frozenset({ConfigSubjectKind.COMPUTER})
READ_REQUIRES_REGISTRY: Final = False
_TELEGRAM = "telegram"
_RETIRED_FIELDS: Final = ("alert_username", "alert_chat_id")


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Drop `telegram.alert_username` and `telegram.alert_chat_id`; the values are dropped, not moved, because nothing consumes them."""
    telegram = document.get(_TELEGRAM)
    if not isinstance(telegram, MutableMapping):
        return
    for field in _RETIRED_FIELDS:
        telegram.pop(field, None)
