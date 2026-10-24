"""Project workflow snapshots onto the issue fields collaborators see on GitHub."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from teleclaude.config.identity_schema import PersonEntry
from teleclaude.config.loader import load_person_config_for_entry
from teleclaude.config.schema import PersonConfig
from teleclaude.constants import TodoStatus
from teleclaude.core.organization import roster_people
from teleclaude.core.person_message_recipients import RecipientUnresolvableError, resolve_person_message_recipients
from teleclaude.core.todos_db._working_copy import WorkingCopyItemSnapshot
from teleclaude.core.workflow_store.github_record import WorkflowField, WorkflowTodoStatus
from teleclaude.types.creation_record import Lineage
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todo_kind import TodoKind

_EMPTY = ""
INPUT_ARTIFACT_NAME = "input"
_KIND = "kind"
_CREATIVE = "creative"
_HOLD = "hold"
_EN_DASH_INPUT = " — Input"
_ENCODING = "utf-8"
_LINE_ENDINGS = "\r\n"
_MARKDOWN_HEADING_MARKER = "#"
_MARKDOWN_HEADING_SEPARATOR = " "
PROJECTION_JSON_SEPARATORS = (",", ":")


class ProjectionPart(StrEnum):
    """Closed set of independently reflected GitHub issue fields."""

    TITLE = "title"
    BODY = "body"
    STATE = "state"
    STATE_REASON = "state_reason"
    LABELS = "labels"
    ISSUE_TYPE = "issue_type"
    ASSIGNEES = "assignees"
    PARENT = "parent"
    PARENT_ISSUE_ID = "parent_issue_id"
    PARENT_ISSUE_NUMBER = "parent_issue_number"
    BLOCKED_BY = "blocked_by"
    BLOCKED_BY_ISSUE_IDS = "blocked_by_issue_ids"


ISSUE_FIELD_PARTS = frozenset(
    {
        ProjectionPart.TITLE,
        ProjectionPart.BODY,
        ProjectionPart.STATE,
        ProjectionPart.LABELS,
        ProjectionPart.ISSUE_TYPE,
        ProjectionPart.ASSIGNEES,
    }
)


class GitHubIssueType(StrEnum):
    """Closed set of repository issue types used by the workflow projection."""

    FEATURE = "Feature"
    CHANGE = "Change"
    BUG = "Bug"


class IssueLabelName(StrEnum):
    """Closed set of workflow-owned GitHub label names."""

    PREP_DIAGNOSIS = "stage:prep.diagnosis"
    PREP_SPEC = "stage:prep.spec"
    PREP_SPEC_REVIEW = "stage:prep.spec-review"
    PREP_SPEC_APPROVAL = "stage:prep.spec-approval"
    PREP_DESIGN = "stage:prep.design"
    PREP_DESIGN_REVIEW = "stage:prep.design-review"
    PREP_PLAN = "stage:prep.plan"
    PREP_PLAN_REVIEW = "stage:prep.plan-review"
    PREP_BLOCKED = "stage:prep.blocked"
    PREP_READY = "stage:prep.ready"
    WORK_BUILD = "stage:work.build"
    WORK_REVIEW = "stage:work.review"
    INTEGRATE_QUEUED = "stage:integrate.queued"
    STATUS_ICEBOX = "status:icebox"
    STATUS_ON_HOLD = "status:on-hold"


_STAGE_LABELS: dict[LifecyclePhase, IssueLabelName | None] = {
    LifecyclePhase.DRAFT: None,
    LifecyclePhase.PRD_DRAFTING: IssueLabelName.PREP_SPEC,
    LifecyclePhase.PRD_REVIEW: IssueLabelName.PREP_SPEC_REVIEW,
    LifecyclePhase.PRD_HUMAN_APPROVAL: IssueLabelName.PREP_SPEC_APPROVAL,
    LifecyclePhase.ARCHITECTURE_DRAFTING: IssueLabelName.PREP_DESIGN,
    LifecyclePhase.ARCHITECTURE_REVIEW: IssueLabelName.PREP_DESIGN_REVIEW,
    LifecyclePhase.DIAGNOSE: IssueLabelName.PREP_DIAGNOSIS,
    LifecyclePhase.PLAN_DRAFTING: IssueLabelName.PREP_PLAN,
    LifecyclePhase.PLAN_REVIEW: IssueLabelName.PREP_PLAN_REVIEW,
    LifecyclePhase.TASK_PLAN_DRAFTING: None,
    LifecyclePhase.PREPARED: IssueLabelName.PREP_READY,
    LifecyclePhase.BLOCKED: IssueLabelName.PREP_BLOCKED,
    LifecyclePhase.BUILD_STARTED: IssueLabelName.WORK_BUILD,
    LifecyclePhase.BUILD_COMPLETE: IssueLabelName.WORK_REVIEW,
    LifecyclePhase.REVIEW_CHANGES_REQUESTED: IssueLabelName.WORK_BUILD,
    LifecyclePhase.REVIEW_APPROVED: IssueLabelName.INTEGRATE_QUEUED,
    LifecyclePhase.FINALIZE_READY: IssueLabelName.INTEGRATE_QUEUED,
    LifecyclePhase.DELIVERED: None,
    LifecyclePhase.TASK_RUNNING: None,
}
_ISSUE_TYPE_BY_KIND: dict[TodoKind, GitHubIssueType] = {
    TodoKind.FEATURE: GitHubIssueType.FEATURE,
    TodoKind.CHANGE: GitHubIssueType.CHANGE,
    TodoKind.BUG: GitHubIssueType.BUG,
}
_LABEL_PROPERTIES: dict[IssueLabelName, tuple[str, str]] = {
    IssueLabelName.PREP_DIAGNOSIS: ("#d7af00", "The cause of this bug is being diagnosed."),
    IssueLabelName.PREP_SPEC: ("#d7af00", "The spec is being written."),
    IssueLabelName.PREP_SPEC_REVIEW: ("#d7af00", "The spec is being reviewed."),
    IssueLabelName.PREP_SPEC_APPROVAL: ("#d7af00", "The spec waits for a person's approval."),
    IssueLabelName.PREP_DESIGN: ("#d7af00", "The technical design is being written."),
    IssueLabelName.PREP_DESIGN_REVIEW: ("#d7af00", "The technical design is being reviewed."),
    IssueLabelName.PREP_PLAN: ("#d7af00", "The implementation plan is being written."),
    IssueLabelName.PREP_PLAN_REVIEW: ("#d7af00", "The implementation plan is being reviewed."),
    IssueLabelName.PREP_BLOCKED: ("#d7af00", "Preparation is stuck and needs a decision."),
    IssueLabelName.PREP_READY: ("#5faf5f", "Prepared and ready to be built."),
    IssueLabelName.WORK_BUILD: ("#d7af00", "Being built, or fixed after review."),
    IssueLabelName.WORK_REVIEW: ("#d7af00", "The build is being reviewed."),
    IssueLabelName.INTEGRATE_QUEUED: ("#5faf5f", "Approved and waiting to be merged."),
    IssueLabelName.STATUS_ICEBOX: ("#5fafd7", "Parked in the icebox; not planned for now."),
    IssueLabelName.STATUS_ON_HOLD: ("#d75f00", "Deliberately paused until someone releases it."),
}


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
class IssueLabel:
    """Repository label properties owned by the workflow projection."""

    name: IssueLabelName
    color: str
    description: str


@dataclass(frozen=True)
class IssueReflection:
    """Complete desired issue projection, including the adapter's relations."""

    title: str
    body: str
    state: IssueState
    state_reason: IssueStateReason
    labels: tuple[IssueLabel, ...]
    issue_type: GitHubIssueType | None
    assignees: tuple[str, ...]
    parent_issue_number: int | None
    parent_issue_id: int | None
    blocked_by_issue_ids: tuple[int, ...]
    digest: str
    projection_digests: Mapping[ProjectionPart, str]


ProjectionQueueEntry = tuple[int, int | None, str, IssueReflection, frozenset[ProjectionPart], str]


def reflect_issue(
    snapshot: WorkingCopyItemSnapshot,
    *,
    parent_issue_number: int | None = None,
    parent_issue_id: int | None = None,
    blocked_by_issue_ids: Sequence[int] = (),
    waiting_assignees: Sequence[str] = (),
) -> IssueReflection:
    """Map one item and its adapter-owned context onto its complete issue projection."""
    state = _state_mapping(snapshot.state)
    kind = _todo_kind(state)
    issue_type = _ISSUE_TYPE_BY_KIND.get(kind) if kind is not None else None
    is_repository_item = is_repository_work(snapshot.state)
    is_holder = snapshot.todo.get(WorkflowField.STATUS) == TodoStatus.HOLDER
    phase = _lifecycle_phase(state)
    held = state.get(_HOLD) is True
    iceboxed = snapshot.todo.get(WorkflowField.STATUS) == TodoStatus.ICEBOX
    status = snapshot.todo.get(WorkflowField.STATUS)
    input_body = _input_content(snapshot)
    title, body = _title_and_body(input_body, str(snapshot.todo.get(WorkflowField.SLUG, _EMPTY)))

    labels: list[IssueLabel] = []
    if is_repository_item:
        if not iceboxed and not is_holder and phase is not None:
            stage = _STAGE_LABELS[phase]
            if stage is not None:
                labels.append(_stage_label(stage))
        if iceboxed:
            labels.append(_status_label(IssueLabelName.STATUS_ICEBOX))
        elif held:
            labels.append(_status_label(IssueLabelName.STATUS_ON_HOLD))

    if not is_repository_item:
        issue_state = IssueState.CLOSED
        reason = IssueStateReason.NOT_PLANNED
    elif status == WorkflowTodoStatus.DELIVERED:
        issue_state = IssueState.CLOSED
        reason = IssueStateReason.COMPLETED
    elif status in {WorkflowTodoStatus.REMOVED, WorkflowTodoStatus.PURGED}:
        issue_state = IssueState.CLOSED
        reason = IssueStateReason.NOT_PLANNED
    else:
        issue_state = IssueState.OPEN
        reason = IssueStateReason.REOPENED

    if not is_repository_item:
        issue_type = None
        parent_issue_id = None
        parent_issue_number = None
        blocked_by_issue_ids = ()
        waiting_assignees = ()
    elif is_holder:
        issue_type = None

    assignees = set(waiting_assignees)
    if is_repository_item and _lifecycle_phase(state) is LifecyclePhase.PRD_HUMAN_APPROVAL:
        assignees.update(_spec_approval_assignees(snapshot))

    projection = {
        ProjectionPart.TITLE: title,
        ProjectionPart.BODY: body,
        ProjectionPart.STATE: str(issue_state),
        ProjectionPart.STATE_REASON: str(reason),
        ProjectionPart.LABELS: [(label.name.value, label.color, label.description) for label in labels],
        ProjectionPart.ISSUE_TYPE: issue_type.value if issue_type is not None else None,
        ProjectionPart.ASSIGNEES: sorted(assignees),
        ProjectionPart.PARENT_ISSUE_ID: parent_issue_id,
        ProjectionPart.PARENT_ISSUE_NUMBER: parent_issue_number,
        ProjectionPart.BLOCKED_BY_ISSUE_IDS: sorted(set(blocked_by_issue_ids)),
    }
    projection_digests = {
        ProjectionPart.TITLE: _digest(title),
        ProjectionPart.BODY: _digest(body),
        ProjectionPart.STATE: _digest((projection[ProjectionPart.STATE], projection[ProjectionPart.STATE_REASON])),
        ProjectionPart.LABELS: _digest(projection[ProjectionPart.LABELS]),
        ProjectionPart.ISSUE_TYPE: _digest(projection[ProjectionPart.ISSUE_TYPE]),
        ProjectionPart.ASSIGNEES: _digest(projection[ProjectionPart.ASSIGNEES]),
        ProjectionPart.PARENT: _digest(
            (projection[ProjectionPart.PARENT_ISSUE_NUMBER], projection[ProjectionPart.PARENT_ISSUE_ID])
        ),
        ProjectionPart.BLOCKED_BY: _digest(projection[ProjectionPart.BLOCKED_BY_ISSUE_IDS]),
    }
    digest = _digest(projection)
    return IssueReflection(
        title=title,
        body=body,
        state=issue_state,
        state_reason=reason,
        labels=tuple(labels),
        issue_type=issue_type,
        assignees=tuple(sorted(assignees)),
        parent_issue_id=parent_issue_id,
        parent_issue_number=parent_issue_number,
        blocked_by_issue_ids=tuple(sorted(set(blocked_by_issue_ids))),
        digest=digest,
        projection_digests=projection_digests,
    )


def is_repository_work(workflow_state: Mapping[str, object] | None) -> bool:
    """Return whether the adapter publishes this item's kind and creative-track state."""
    state = _state_mapping(workflow_state)
    creative = state.get(_CREATIVE)
    return state.get(_KIND) != TodoKind.TASK and not (isinstance(creative, Mapping) and bool(creative))


def changed_projection_parts(
    reflection: IssueReflection, previous: Mapping[ProjectionPart, str] | None
) -> frozenset[ProjectionPart]:
    """Name projection fields whose desired digest differs from the last successful write."""
    if previous is None:
        return frozenset(reflection.projection_digests)
    return frozenset(name for name, digest in reflection.projection_digests.items() if previous.get(name) != digest)


def parse_projection_digests(value: object) -> Mapping[ProjectionPart, str] | None:
    """Decode the optional persisted projection fingerprint map."""
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or any(not isinstance(item, str) for item in parsed.values()):
        return None
    try:
        return {ProjectionPart(key): item for key, item in parsed.items()}
    except ValueError:
        return None


def serialize_projection_digests(value: Mapping[ProjectionPart, str]) -> str:
    """Serialize the persisted projection map with its canonical compact format."""
    return json.dumps(value, sort_keys=True, separators=PROJECTION_JSON_SEPARATORS)


def platform_issue_labels() -> tuple[IssueLabel, ...]:
    """Return each current label definition once, in stable repository order."""
    stage_names = {stage for stage in _STAGE_LABELS.values() if stage is not None}
    labels = [_stage_label(name) for name in stage_names]
    labels.extend((_status_label(IssueLabelName.STATUS_ICEBOX), _status_label(IssueLabelName.STATUS_ON_HOLD)))
    return tuple(sorted(labels, key=lambda label: label.name.value))


def github_handles_for_person_slugs(person_slugs: Sequence[str]) -> tuple[str, ...]:
    """Resolve only explicitly configured GitHub handles for the selected roster people."""
    if not person_slugs:
        return ()
    roster = dict(roster_people())
    return tuple(
        sorted(
            {
                person.github.identity.handle
                for slug in person_slugs
                if (person := roster.get(slug)) is not None and person.github.identity.handle
            }
        )
    )


def _stage_label(name: IssueLabelName) -> IssueLabel:
    color, description = _LABEL_PROPERTIES[name]
    return IssueLabel(name, color, description)


def _status_label(name: IssueLabelName) -> IssueLabel:
    color, description = _LABEL_PROPERTIES[name]
    return IssueLabel(name, color, description)


def _todo_kind(state: Mapping[str, object]) -> TodoKind | None:
    raw = state.get(_KIND)
    try:
        return TodoKind(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def _lifecycle_phase(state: Mapping[str, object]) -> LifecyclePhase | None:
    raw = state.get(WorkflowField.LIFECYCLE_PHASE)
    try:
        return LifecyclePhase(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def _spec_approval_assignees(snapshot: WorkingCopyItemSnapshot) -> tuple[str, ...]:
    lineage = snapshot.todo.get(WorkflowField.LINEAGE)
    principal = Lineage.root_of(lineage if isinstance(lineage, str) else None)
    try:
        recipients = resolve_person_message_recipients(None, principal)
    except RecipientUnresolvableError:
        return ()
    handles: set[str] = set()
    roster: dict[str, PersonConfig] | None = None
    for recipient in recipients:
        if isinstance(recipient, PersonEntry):
            person = load_person_config_for_entry(recipient)
        else:
            if roster is None:
                roster = dict(roster_people())
            person = roster.get(recipient)
        handle = person.github.identity.handle if person is not None else None
        if handle:
            handles.add(handle)
    return tuple(sorted(handles))


def _input_content(snapshot: WorkingCopyItemSnapshot) -> str:
    for artifact in snapshot.artifacts:
        if artifact.get(WorkflowField.NAME) == INPUT_ARTIFACT_NAME:
            content = artifact.get(WorkflowField.CONTENT)
            return content if isinstance(content, str) else _EMPTY
    return _EMPTY


def _title_and_body(content: str, slug: str) -> tuple[str, str]:
    generated = slug + _EN_DASH_INPUT
    title = next(
        (heading for line in content.splitlines() if (heading := _heading_text(line)) and heading != generated), slug
    )
    body = _EMPTY.join(line for line in content.splitlines(keepends=True) if _heading_text(line) != generated)
    return title, body


def _heading_text(line: str) -> str | None:
    stripped = line.lstrip().rstrip(_LINE_ENDINGS)
    heading_end = len(stripped) - len(stripped.lstrip(_MARKDOWN_HEADING_MARKER))
    if heading_end == 0 or heading_end >= len(stripped) or stripped[heading_end] != _MARKDOWN_HEADING_SEPARATOR:
        return None
    heading = stripped[heading_end:].strip()
    return heading or None


def _state_mapping(workflow_state: Mapping[str, object] | None) -> Mapping[str, object]:
    if workflow_state is None:
        return {}
    value = workflow_state.get(WorkflowField.STATE)
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return cast(Mapping[str, object], parsed) if isinstance(parsed, dict) else {}


def _digest(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=PROJECTION_JSON_SEPARATORS, default=str)
    return hashlib.sha256(serialized.encode(_ENCODING)).hexdigest()
