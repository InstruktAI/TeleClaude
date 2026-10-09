"""Retire the `hooks.subscriptions` section from project documents."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 19
KINDS: Final = frozenset({ConfigSubjectKind.PROJECT})
READ_REQUIRES_REGISTRY: Final = False
_HOOKS = "hooks"
_SUBSCRIPTIONS = "subscriptions"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Drop `hooks.subscriptions`, and the `hooks` mapping when that leaves it empty; the value is dropped, not moved, because nothing consumes it."""
    hooks = document.get(_HOOKS)
    if not isinstance(hooks, MutableMapping):
        return
    hooks.pop(_SUBSCRIPTIONS, None)
    if not hooks:
        document.pop(_HOOKS, None)
