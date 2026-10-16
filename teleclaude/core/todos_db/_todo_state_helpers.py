"""State projections used to validate todo transitions."""

from __future__ import annotations

import json
from typing import TypedDict, cast

from teleclaude.core.todos_db._models import Todo, TodoStateModel
from teleclaude.core.todos_db._upcycle import upcycle_state_dict
from teleclaude.types.state_value import StateValue


class EntryUpdates(TypedDict, total=False):
    """Subset of todo fields eligible for idempotent update."""

    group_id: str
    description: str
    updated_at: str


def collect_entry_updates(existing: Todo, *, group_id: str | None, description: str | None) -> EntryUpdates:
    """Build a dict of fields that differ from the existing entry."""
    values = EntryUpdates()
    if group_id is not None and existing.group_id != group_id:
        values["group_id"] = group_id
    if description is not None and existing.description != description:
        values["description"] = description
    return values


def readiness_state_fields(state_model: TodoStateModel | None) -> tuple[str | None, str | None]:
    """Read the kind and lifecycle phase used to validate holder transitions."""
    if state_model is None:
        return None, None
    try:
        state = json.loads(state_model.state)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(state, dict):
        return None, None
    payload = upcycle_state_dict(cast(dict[str, StateValue], state))
    kind = payload.get("kind")
    lifecycle_phase = payload.get("lifecycle_phase")
    return (
        kind if isinstance(kind, str) else None,
        lifecycle_phase if isinstance(lifecycle_phase, str) else None,
    )
