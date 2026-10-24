"""One workflow-to-issue reflection mapping for push and repair."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from teleclaude.core.todos_db._working_copy import WorkingCopyItemSnapshot
from teleclaude.core.workflow_store.github_record import WorkflowField, WorkflowTodoStatus

_EMPTY = ""
INPUT_ARTIFACT_NAME = "input"
_PHASE_LABEL = "teleclaude:phase-{}"
_CLAIMED_LABEL = "teleclaude:claimed"


class IssueState(StrEnum):
    """Closed set of issue lifecycle values reflected to GitHub."""

    OPEN = "open"
    CLOSED = "closed"


class IssueStateReason(StrEnum):
    """Closed set of state reasons used by GitHub issue updates."""

    COMPLETED = "completed"
    NOT_PLANNED = "not_planned"
    REOPENED = "reopened"


@dataclass(frozen=True)
class IssueReflection:
    """Fields the GitHub issue mirrors from one workflow snapshot."""

    title: str
    body: str
    state: IssueState
    state_reason: IssueStateReason
    labels: tuple[str, ...]


def reflect_issue(snapshot: WorkingCopyItemSnapshot) -> IssueReflection:
    """Map one item snapshot to its public issue fields."""
    state = _state_mapping(snapshot)
    phase = str(
        state.get(WorkflowField.LIFECYCLE_PHASE, snapshot.todo.get(WorkflowField.STATUS, WorkflowTodoStatus.ACTIVE))
    )
    labels = [_PHASE_LABEL.format(phase)]
    if state.get(WorkflowField.ACTIVE_RUNNER):
        labels.append(_CLAIMED_LABEL)
    status = snapshot.todo.get(WorkflowField.STATUS)
    if status == WorkflowTodoStatus.DELIVERED:
        issue_state = IssueState.CLOSED
        reason = IssueStateReason.COMPLETED
    elif status in {WorkflowTodoStatus.REMOVED, WorkflowTodoStatus.PURGED}:
        issue_state = IssueState.CLOSED
        reason = IssueStateReason.NOT_PLANNED
    else:
        issue_state = IssueState.OPEN
        reason = IssueStateReason.REOPENED
    return IssueReflection(
        title=str(snapshot.todo.get(WorkflowField.SLUG, _EMPTY)),
        body=_input_content(snapshot),
        state=issue_state,
        state_reason=reason,
        labels=tuple(labels),
    )


def _input_content(snapshot: WorkingCopyItemSnapshot) -> str:
    for artifact in snapshot.artifacts:
        if artifact.get(WorkflowField.NAME) == INPUT_ARTIFACT_NAME:
            content = artifact.get(WorkflowField.CONTENT)
            return content if isinstance(content, str) else _EMPTY
    return _EMPTY


def _state_mapping(snapshot: WorkingCopyItemSnapshot) -> Mapping[str, object]:
    if snapshot.state is None:
        return {}
    value = snapshot.state.get(WorkflowField.STATE)
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return cast(Mapping[str, object], parsed) if isinstance(parsed, dict) else {}
