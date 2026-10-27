"""Derive the board item an item's record reflects onto the project's GitHub board.

A pure derivation like `reflect_pull_request`: it reads the item's working-copy snapshot and never GitHub.
The lane and the needs-you marker come from the lifecycle's own predicates; this module only maps them.
Applying the result is `github_board_queue`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from teleclaude.constants import TodoStatus
from teleclaude.core.next_machine.lifecycle import (
    effective_hold,
    is_in_work_lane,
    pending_approval_gate,
    plan_review_current,
)
from teleclaude.core.todos_db._working_copy import WorkingCopyItemSnapshot
from teleclaude.core.workflow_store.github_record import WorkflowField
from teleclaude.core.workflow_store.github_reflection import is_repository_work, stable_digest
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todos import TodoState

ABSENT_DIGEST = stable_digest(None)
"""The digest recorded for an item verified to have no board item, so absence is checked once."""


class BoardLane(StrEnum):
    """The board's lanes, in board order; each value is the Status option name shown on GitHub."""

    ICEBOX = "Icebox"
    PREPARE = "Prepare"
    WORK = "Work"
    DELIVERED = "Delivered"


@dataclass(frozen=True)
class BoardItemReflection:
    """One item as it should appear on the board: its lane and whether it waits on a person."""

    lane: BoardLane
    needs_you: bool
    digest: str


def reflect_board_item(snapshot: WorkingCopyItemSnapshot) -> BoardItemReflection | None:
    """Map one item onto the board, or None when it has no board item.

    Raises when an active or iceboxed item's workflow state does not validate: the caller owes the
    item's board reflection and the next refresh derives it again.
    """
    if not is_repository_work(snapshot.state):
        return None
    status = snapshot.todo.get(WorkflowField.STATUS)
    if status == TodoStatus.DELIVERED:
        return _reflection(BoardLane.DELIVERED, needs_you=False)
    if status not in {TodoStatus.ACTIVE, TodoStatus.ICEBOX}:
        return None
    model = TodoState.model_validate(_state_document(snapshot))
    needs_you = _waits_on_person(model)
    if status == TodoStatus.ICEBOX:
        return _reflection(BoardLane.ICEBOX, needs_you=needs_you)
    in_work = is_in_work_lane(model.lifecycle_phase, plan_review_is_current=plan_review_current(model))
    return _reflection(BoardLane.WORK if in_work else BoardLane.PREPARE, needs_you=needs_you)


def _waits_on_person(model: TodoState) -> bool:
    """Return whether the platform will not move the item and only a person can."""
    if pending_approval_gate(model) is not None:
        return True
    stopped = effective_hold(hold=model.hold) or model.lifecycle_phase == LifecyclePhase.BLOCKED
    return stopped and not model.active_runner


def _reflection(lane: BoardLane, *, needs_you: bool) -> BoardItemReflection:
    return BoardItemReflection(lane=lane, needs_you=needs_you, digest=stable_digest((lane.value, needs_you)))


def _state_document(snapshot: WorkingCopyItemSnapshot) -> Mapping[str, object]:
    value = snapshot.state.get(WorkflowField.STATE) if snapshot.state is not None else None
    parsed = json.loads(value) if isinstance(value, str) else {}
    return cast(Mapping[str, object], parsed)
