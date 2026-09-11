"""Review-pass admission and limit enforcement for lifecycle review loops."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from teleclaude.core.next_machine._types import DEFAULT_MAX_REVIEW_ROUNDS, PreparePhase, StateValue
from teleclaude.core.next_machine.output_formatting import format_error
from teleclaude.core.next_machine.review_evidence import REVIEW_EVIDENCE_ARTIFACTS
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.types.todos import BuildReviewState, ReviewContinuation, ReviewHaltClassification, ReviewVerdictState

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

_REVIEW_CAUSED_CLASSIFICATIONS = frozenset(
    {ReviewHaltClassification.INCOMPLETE_REVIEW, ReviewHaltClassification.NOISY_REVIEW}
)
_CONTINUATION_STAMP_TEMPLATE = (
    "telec todo stamp {slug} --review-continuation --phase {phase} "
    "--reason '<classification>: <evidence that the next attempt differs>'"
)


class ReviewPhase(StrEnum):
    """Closed vocabulary for lifecycle phases that dispatch reviewers."""

    PRD = "prd_review"
    ARCHITECTURE = "architecture_review"
    PLAN = "plan_review"
    BUILD = "build_review"


_PREPARE_REVIEW_PHASES: dict[PreparePhase, ReviewPhase] = {
    PreparePhase.PRD_REVIEW: ReviewPhase.PRD,
    PreparePhase.ARCHITECTURE_REVIEW: ReviewPhase.ARCHITECTURE,
    PreparePhase.PLAN_REVIEW: ReviewPhase.PLAN,
}
_LIMIT_MESSAGE_TEMPLATE = (
    "Review round limit reached for {slug}: phase={phase}, admitted={admitted}, max={maximum}. "
    "No reviewer is dispatched. Read the current review evidence before classifying the halted loop."
)
_READ_REVIEW_EVIDENCE_TEMPLATE = "telec todo artifacts read {slug} {report_artifact}"
REVIEW_ROUND_LIMIT_CODE = "REVIEW_ROUND_LIMIT"


@dataclass(frozen=True)
class ReviewAdmission:
    """Deterministic admission state for a single review-dispatch attempt."""

    phase: ReviewPhase
    admitted: int
    candidate: int
    maximum: int
    cumulative_candidate: int
    report_artifact: str
    continuation: ReviewContinuation | None = None

    @property
    def allowed(self) -> bool:
        """Return whether the candidate pass fits within the hard cap."""
        return self.candidate <= self.maximum

    @property
    def requires_fresh_reviewer_session(self) -> bool:
        """Return whether the admitting continuation requires a different reviewer session."""
        return self.continuation is not None and self.continuation.classification in _REVIEW_CAUSED_CLASSIFICATIONS


def prepare_review_phase(phase: PreparePhase) -> ReviewPhase | None:
    """Return the review phase represented by a prepare phase, when it has one."""
    return _PREPARE_REVIEW_PHASES.get(phase)


def prepare_review_admission(state: dict[str, StateValue], phase: PreparePhase) -> ReviewAdmission | None:
    """Describe the next prepare-review admission without mutating state."""
    review_phase = prepare_review_phase(phase)
    if review_phase is None:
        return None
    review = StateWriter(state).review(review_phase.value)
    return prepare_cycle_admission(review_phase, review)


def prepare_cycle_admission(phase: ReviewPhase, review: ReviewVerdictState) -> ReviewAdmission:
    """Project one prepare review's cumulative history onto its current cycle."""
    return _admission_for(
        phase,
        review.rounds,
        review.continuations,
        round_offset=review.cycle.round_offset,
        continuation_offset=review.cycle.continuation_offset,
    )


def build_review_admission(state: dict[str, StateValue]) -> ReviewAdmission:
    """Describe the next build-review admission without mutating state."""
    review = StateWriter(state).state.build_review
    return build_cycle_admission(review)


def build_cycle_admission(review: BuildReviewState) -> ReviewAdmission:
    """Project build-review history with its existing phase-wide arithmetic."""
    return _admission_for(ReviewPhase.BUILD, review.round, review.continuations)


async def admit_prepare_review(
    todos_db: TodosDb,
    slug: str,
    state: dict[str, StateValue],
    admission: ReviewAdmission,
) -> None:
    """Persist one admitted prepare pass before its reviewer instruction is emitted."""
    writer = StateWriter(state)
    review = writer.review(admission.phase.value)
    audit = writer.audit_entry(admission.phase.value)
    review.rounds = admission.cumulative_candidate
    audit.rounds = admission.cumulative_candidate
    await _commit(writer, todos_db, slug, state)


async def admit_build_review(
    todos_db: TodosDb,
    slug: str,
    state: dict[str, StateValue],
    admission: ReviewAdmission,
) -> None:
    """Persist one admitted build pass before fresh or reused reviewer dispatch."""
    writer = StateWriter(state)
    writer.state.build_review.round = admission.candidate
    await _commit(writer, todos_db, slug, state)


def format_review_round_limit(slug: str, admission: ReviewAdmission) -> str:
    """Expose deterministic cap evidence without deciding review substance."""
    message = _LIMIT_MESSAGE_TEMPLATE.format(
        slug=slug,
        phase=admission.phase.value,
        admitted=admission.admitted,
        maximum=admission.maximum,
    )
    next_call = _READ_REVIEW_EVIDENCE_TEMPLATE.format(slug=slug, report_artifact=admission.report_artifact)
    continuation_call = _CONTINUATION_STAMP_TEMPLATE.format(slug=slug, phase=admission.phase.value)
    return format_error(REVIEW_ROUND_LIMIT_CODE, message, next_call=f"{next_call}; {continuation_call}")


def _admission_for(
    phase: ReviewPhase,
    admitted: int,
    continuations: list[ReviewContinuation],
    *,
    round_offset: int = 0,
    continuation_offset: int = 0,
) -> ReviewAdmission:
    """Construct the next admission from the phase-owned persisted counter.

    The allowance grows additively by one for every recorded continuation, so
    the count never resets. The admitting continuation is the most recently
    recorded one, carried only when the candidate pass exceeds the hard cap —
    i.e. only when a continuation is what makes this candidate admissible.
    """
    report_artifact = REVIEW_EVIDENCE_ARTIFACTS[phase.value].report_artifact_name
    cycle_admitted = admitted - round_offset
    cycle_continuations = continuations[continuation_offset:]
    candidate = cycle_admitted + 1
    maximum = DEFAULT_MAX_REVIEW_ROUNDS + len(cycle_continuations)
    admitting_continuation = (
        cycle_continuations[-1] if cycle_continuations and candidate > DEFAULT_MAX_REVIEW_ROUNDS else None
    )
    return ReviewAdmission(
        phase=phase,
        admitted=cycle_admitted,
        candidate=candidate,
        maximum=maximum,
        cumulative_candidate=admitted + 1,
        report_artifact=report_artifact,
        continuation=admitting_continuation,
    )


async def _commit(
    writer: StateWriter,
    todos_db: TodosDb,
    slug: str,
    state: dict[str, StateValue],
) -> None:
    """Persist the typed mutation and refresh the caller's state snapshot."""
    payload = await writer.commit(todos_db, slug)
    state.clear()
    state.update(payload)
