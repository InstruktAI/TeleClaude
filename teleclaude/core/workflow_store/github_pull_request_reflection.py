"""Derive the pull request and reviews an item's record reflects onto GitHub.

A pure derivation like `reflect_issue`: it reads the item's working-copy snapshot, including its
`build_review_stamp` events, and never GitHub. Applying it is `github_pull_request_apply`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from teleclaude.constants import ARTIFACT_REVIEW_FINDINGS
from teleclaude.core.roles import RoleName
from teleclaude.core.todos_db._working_copy import WorkingCopyItemSnapshot
from teleclaude.core.workflow_store.github_pull_request_io import GitHubReviewEvent
from teleclaude.core.workflow_store.github_record import (
    CommentEnvelopeAction,
    CommentEnvelopeField,
    WorkflowField,
    WorkflowTodoStatus,
    comment_envelope_fields,
    render_comment_envelope,
)
from teleclaude.core.workflow_store.github_reflection import (
    is_repository_work,
    issue_title,
    stable_digest,
)
from teleclaude.types.lifecycle import WORK_LIFECYCLE_PHASES, LifecyclePhase
from teleclaude.types.todos import BuildReviewDetail, TodoEventKind

_EMPTY = ""
_STATE_KEY_EVENTS = "events"
_STATE_KEY_BUILD_START = "build_start_base_sha"
_EVENT_KIND = "kind"
_EVENT_ACTOR = "actor"
_EVENT_DETAILS = "details"
_HOLDER_STATUS = "holder"
_BODY_LIMIT = 60_000
_TRUNCATION_NOTE = "\n\n_(Truncated; the full report is on the item's issue.)_"
_CLOSING_LINE = "Closes #{}"
_LINE_BREAK = "\n"
_BLANK_LINE = "\n\n"


class PullRequestStage(StrEnum):
    """What the item's pull request should be on GitHub."""

    OPEN = "open"
    DELIVERED = "delivered"
    CLOSED = "closed"


class _StampedVerdict(StrEnum):
    """Build review verdict values as the stamp records them."""

    APPROVE = "approve"
    CHANGES_REQUESTED = "changes_requested"


_REVIEW_EVENTS: dict[str, GitHubReviewEvent] = {
    _StampedVerdict.APPROVE: GitHubReviewEvent.APPROVE,
    _StampedVerdict.CHANGES_REQUESTED: GitHubReviewEvent.REQUEST_CHANGES,
}


@dataclass(frozen=True)
class ReviewReflection:
    """One build review as it should appear on the pull request."""

    round: int
    commit: str
    event: GitHubReviewEvent
    body: str


@dataclass(frozen=True)
class PullRequestReflection:
    """Complete desired pull request for one item, including its reviews."""

    issue_number: int
    branch: str
    title: str
    body: str
    stage: PullRequestStage
    delivered_commit: str
    reviews: tuple[ReviewReflection, ...]
    digest: str


def reflect_pull_request(snapshot: WorkingCopyItemSnapshot, issue_number: int) -> PullRequestReflection | None:
    """Map one item onto its pull request, or None when it has none to show on GitHub."""
    if not is_repository_work(snapshot.state):
        return None
    status = snapshot.todo.get(WorkflowField.STATUS)
    if status == _HOLDER_STATUS:
        return None
    state = _state(snapshot)
    if status == WorkflowTodoStatus.DELIVERED:
        stage = PullRequestStage.DELIVERED
    elif status in {WorkflowTodoStatus.REMOVED, WorkflowTodoStatus.PURGED}:
        stage = PullRequestStage.CLOSED
    elif _build_started(state):
        stage = PullRequestStage.OPEN
    else:
        return None

    branch = str(snapshot.todo.get(WorkflowField.SLUG, _EMPTY))
    title = issue_title(snapshot)
    body = pull_request_envelope(issue_number) + _BLANK_LINE + _CLOSING_LINE.format(issue_number)
    delivered_commit = str(snapshot.todo.get(WorkflowField.DELIVERED_COMMIT) or _EMPTY)
    reviews = _reviews(snapshot, state)
    digest = stable_digest((stage.value, title, body, delivered_commit))
    return PullRequestReflection(
        issue_number=issue_number,
        branch=branch,
        title=title,
        body=body,
        stage=stage,
        delivered_commit=delivered_commit,
        reviews=reviews,
        digest=digest,
    )


def pull_request_envelope(issue_number: int) -> str:
    """Render the opening line that ties a pull request to its item's issue."""
    return render_comment_envelope(
        (
            (CommentEnvelopeField.ACTION, CommentEnvelopeAction.PULL_REQUEST),
            (CommentEnvelopeField.ISSUE, issue_number),
        )
    )


def delivered_comment(commit: str) -> str:
    """Render the comment that names the commit that delivered the item."""
    return render_comment_envelope(
        ((CommentEnvelopeField.ACTION, CommentEnvelopeAction.DELIVERED), (CommentEnvelopeField.COMMIT, commit))
    )


def opens_with_pull_request_envelope(body: str, issue_number: int) -> bool:
    """Tell whether a pull request body belongs to the item whose issue is `issue_number`."""
    return body.split(_LINE_BREAK, 1)[0].strip() == pull_request_envelope(issue_number)


def is_delivered_comment(body: str) -> bool:
    """Tell whether a comment body opens with the envelope that names the delivered commit."""
    return comment_envelope_fields(body).get(CommentEnvelopeField.ACTION) == CommentEnvelopeAction.DELIVERED


def review_round(body: str) -> int | None:
    """Read the round a review's opening envelope names; None for a body that is not a review envelope."""
    fields = comment_envelope_fields(body)
    if fields.get(CommentEnvelopeField.ACTION) != CommentEnvelopeAction.REVIEW:
        return None
    value = fields.get(CommentEnvelopeField.ROUND)
    return int(value) if value is not None and value.isascii() and value.isdecimal() else None


def _reviews(snapshot: WorkingCopyItemSnapshot, state: Mapping[str, object]) -> tuple[ReviewReflection, ...]:
    by_round: dict[int, ReviewReflection] = {}
    events = state.get(_STATE_KEY_EVENTS)
    for event in events if isinstance(events, list) else ():
        if not isinstance(event, dict) or event.get(_EVENT_KIND) != TodoEventKind.BUILD_REVIEW_STAMP:
            continue
        details = event.get(_EVENT_DETAILS)
        if not isinstance(details, dict):
            continue
        round_value = details.get(BuildReviewDetail.ROUND)
        commit = details.get(BuildReviewDetail.COMMIT)
        verdict = details.get(BuildReviewDetail.VERDICT)
        report_digest = details.get(BuildReviewDetail.REPORT_DIGEST)
        if (
            isinstance(round_value, bool)
            or not isinstance(round_value, int)
            or not isinstance(commit, str)
            or not commit
            or not isinstance(verdict, str)
            or verdict not in _REVIEW_EVENTS
        ):
            continue
        actor = event.get(_EVENT_ACTOR)
        findings = _findings(snapshot, report_digest) if isinstance(report_digest, str) else _EMPTY
        by_round[round_value] = ReviewReflection(
            round=round_value,
            commit=commit,
            event=_REVIEW_EVENTS[verdict],
            body=_review_body(str(actor or _EMPTY), round_value, findings),
        )
    return tuple(by_round[number] for number in sorted(by_round))


def _review_body(session_id: str, round_number: int, findings: str) -> str:
    envelope = render_comment_envelope(
        (
            (CommentEnvelopeField.SESSION, session_id),
            (CommentEnvelopeField.ROLE, RoleName.REVIEWER.value),
            (CommentEnvelopeField.ACTION, CommentEnvelopeAction.REVIEW),
            (CommentEnvelopeField.ROUND, round_number),
        )
    )
    if len(findings) > _BODY_LIMIT:
        findings = findings[:_BODY_LIMIT] + _TRUNCATION_NOTE
    return envelope + _BLANK_LINE + findings if findings else envelope


def _findings(snapshot: WorkingCopyItemSnapshot, digest: str) -> str:
    for version in snapshot.versions:
        if version.get(WorkflowField.NAME) == ARTIFACT_REVIEW_FINDINGS and version.get(WorkflowField.DIGEST) == digest:
            content = version.get(WorkflowField.CONTENT)
            return content if isinstance(content, str) else _EMPTY
    return _EMPTY


def _build_started(state: Mapping[str, object]) -> bool:
    if state.get(_STATE_KEY_BUILD_START):
        return True
    raw_phase = state.get(WorkflowField.LIFECYCLE_PHASE)
    try:
        phase = LifecyclePhase(raw_phase) if isinstance(raw_phase, str) else None
    except ValueError:
        return False
    return phase in WORK_LIFECYCLE_PHASES


def _state(snapshot: WorkingCopyItemSnapshot) -> Mapping[str, object]:
    if snapshot.state is None:
        return {}
    value = snapshot.state.get(WorkflowField.STATE)
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
