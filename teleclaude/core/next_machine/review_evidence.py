"""Closed ownership of the artifacts that make a review verdict current."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE_REVIEW_FINDINGS,
    ARTIFACT_PLAN_REVIEW_FINDINGS,
    ARTIFACT_PRD_REVIEW_FINDINGS,
    ARTIFACT_REVIEW_FINDINGS,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_PRD,
)
from teleclaude.core.next_machine.git_ops import TodoChangeSinceReview, get_head_commit, todo_change_since
from teleclaude.types.todos import BuildReviewState


class ReviewEvidenceOutcome(StrEnum):
    """Whether a stamped review still binds the current target and report."""

    CURRENT = "current"
    STALE = "stale"
    UNDETERMINED = "undetermined"


class ReviewEvidenceReason(StrEnum):
    """Why a stamped build-review binding is current, stale, or unresolved."""

    EXACT_TARGET = "exact_target"
    CLEAN_UPSTREAM_MERGES = "clean_upstream_merges"
    TODO_CHANGED = "todo_changed"
    REPORT_CHANGED = "report_changed"
    UNBOUND = "unbound"
    UNDETERMINED = "undetermined"


class BuildReviewVerdict(StrEnum):
    """The verdicts a build reviewer may stamp."""

    APPROVE = "approve"
    CHANGES_REQUESTED = "changes_requested"


@dataclass(frozen=True)
class ReviewEvidenceArtifacts:
    """The reviewed target and durable report for one live review phase."""

    target_artifact_key: str | None
    report_artifact_name: str


REVIEW_EVIDENCE_ARTIFACTS: dict[str, ReviewEvidenceArtifacts] = {
    "prd_review": ReviewEvidenceArtifacts(STATE_KEY_PRD, ARTIFACT_PRD_REVIEW_FINDINGS),
    "architecture_review": ReviewEvidenceArtifacts(STATE_KEY_ARCHITECTURE, ARTIFACT_ARCHITECTURE_REVIEW_FINDINGS),
    "plan_review": ReviewEvidenceArtifacts(STATE_KEY_IMPLEMENTATION_PLAN, ARTIFACT_PLAN_REVIEW_FINDINGS),
    "build_review": ReviewEvidenceArtifacts(None, ARTIFACT_REVIEW_FINDINGS),
}

PREPARE_REVIEW_PHASES = tuple(
    phase for phase, artifacts in REVIEW_EVIDENCE_ARTIFACTS.items() if artifacts.target_artifact_key
)
BUILD_REVIEW_PHASE = "build_review"


def build_review_binding_current(
    build_review: BuildReviewState,
    worktree_cwd: str,
    current_report_digest: str,
) -> ReviewEvidenceReason:
    """Classify whether a build-review verdict still binds todo work and its report."""
    if not build_review.reviewed_target_digest or not build_review.review_report_digest:
        return ReviewEvidenceReason.UNBOUND
    if build_review.review_report_digest != current_report_digest:
        return ReviewEvidenceReason.REPORT_CHANGED

    current_head = get_head_commit(worktree_cwd)
    if not current_head:
        return ReviewEvidenceReason.UNDETERMINED
    if build_review.reviewed_target_digest == current_head:
        return ReviewEvidenceReason.EXACT_TARGET

    change = todo_change_since(worktree_cwd, build_review.reviewed_target_digest)
    if change == TodoChangeSinceReview.UNDETERMINED:
        return ReviewEvidenceReason.UNDETERMINED
    if change == TodoChangeSinceReview.CHANGED:
        return ReviewEvidenceReason.TODO_CHANGED
    return ReviewEvidenceReason.CLEAN_UPSTREAM_MERGES
