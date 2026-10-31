"""Retire the maintenance action serving-tolerance field: a commit no longer replaces the daemon, so nothing reads it."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 31
KINDS: Final = frozenset({ConfigSubjectKind.PROJECT})
READ_REQUIRES_REGISTRY: Final = False

_CHECKPOINT_KEY = "checkpoint"
_MAINTENANCE_KEY = "maintenance"
_RUNS_WHILE_SERVING_KEY = "runs_while_serving"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Remove the field from every maintenance action the project declares; a document without it is unchanged."""
    checkpoint = document.get(_CHECKPOINT_KEY)
    if not isinstance(checkpoint, dict):
        return
    maintenance = checkpoint.get(_MAINTENANCE_KEY)
    if not isinstance(maintenance, dict):
        return
    for action in maintenance.values():
        if isinstance(action, dict):
            action.pop(_RUNS_WHILE_SERVING_KEY, None)
