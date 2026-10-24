"""Declare the optional maintenance action serving-tolerance field."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 26
KINDS: Final = frozenset({ConfigSubjectKind.PROJECT})
READ_REQUIRES_REGISTRY: Final = False

_CHECKPOINT_KEY = "checkpoint"
_MAINTENANCE_KEY = "maintenance"
_CONFIG_SCHEMAS_ACTION_ID = "config-schemas"
_COMMAND_KEY = "command"
_RUNS_WHILE_SERVING_KEY = "runs_while_serving"
_CONFIG_SCHEMAS_COMMAND = "teleclaude.core.reconciliation.config_schemas"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Mark this repository's schema publication action as serving-tolerant."""
    checkpoint = document.get(_CHECKPOINT_KEY)
    if not isinstance(checkpoint, dict):
        return
    maintenance = checkpoint.get(_MAINTENANCE_KEY)
    if not isinstance(maintenance, dict):
        return
    action = maintenance.get(_CONFIG_SCHEMAS_ACTION_ID)
    if not isinstance(action, dict):
        return
    command = action.get(_COMMAND_KEY)
    if not isinstance(command, list) or _CONFIG_SCHEMAS_COMMAND not in command:
        return
    action.setdefault(_RUNS_WHILE_SERVING_KEY, True)
