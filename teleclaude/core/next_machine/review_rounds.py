"""Review-pass admission and limit enforcement for lifecycle review loops."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from teleclaude.constants import SlashCommand
from teleclaude.core.next_machine._types import DEFAULT_REVIEW_ROUND_THRESHOLD, PreparePhase, StateValue
from teleclaude.core.next_machine.review_evidence import REVIEW_EVIDENCE_ARTIFACTS
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.types.todos import BuildReviewState, ReviewVerdictState

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


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
_THRESHOLD_REPORT_TEMPLATE = (
    "Review round threshold crossed for {slug}: phase={phase}, admitted={admitted}, "
    f"threshold={{threshold}}. Dispatch an assist against this loop: run /{SlashCommand.ASSIST.value} for "
    "{slug}, phase {phase}, giving it the target, the review evidence ({report_artifact}), "
    "both sessions, and the contract under dispute. Nothing is refused — continue "
    "dispatching or reusing the reviewer as usual."
)


@dataclass(frozen=True)
class ReviewAdmission:
    """Deterministic admission state for a single review-dispatch attempt."""

    phase: ReviewPhase
    admitted: int
    candidate: int
    threshold: int
    cumulative_candidate: int
    report_artifact: str

    @property
    def crossing(self) -> bool:
        """Return whether this candidate pass is the one that first exceeds the threshold."""
        return self.candidate == self.threshold + 1


def prepare_review_phase(phase: PreparePhase) -> ReviewPhase | None:
    """Return the review phase represented by a prepare phase, when it has one."""
    return _PREPARE_REVIEW_PHASES.get(phase)


def prepare_review_admission(state: dict[str, StateValue], phase: PreparePhase) -> ReviewAdmission | None:
    """Describe the next prepare-review admission without mutating state."""
    review_phase = prepare_review_phase(phase)
    if review_phase is None:
        return None
    review = StateWriter(state).review(review_phase.value)
    return _prepare_cycle_admission(review_phase, review)


def _prepare_cycle_admission(phase: ReviewPhase, review: ReviewVerdictState) -> ReviewAdmission:
    """Project one prepare review's cumulative history onto its current cycle."""
    return _admission_for(phase, review.rounds, round_offset=review.cycle.round_offset)


def build_review_admission(state: dict[str, StateValue]) -> ReviewAdmission:
    """Describe the next build-review admission without mutating state."""
    review = StateWriter(state).state.build_review
    return _build_cycle_admission(review)


def _build_cycle_admission(review: BuildReviewState) -> ReviewAdmission:
    """Project build-review history with its existing phase-wide arithmetic."""
    return _admission_for(ReviewPhase.BUILD, review.round)


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


def format_admission_count(admission: ReviewAdmission) -> str:
    """Render the admitted pass and its threshold as two distinct facts.

    Never a fraction: past the threshold, ``round 5/4`` would state a maximum
    the contract deliberately stopped claiming. Naming the pass and the
    threshold separately keeps every render honest about there being no bound.
    """
    return f"pass {admission.candidate}, threshold {admission.threshold}"


def format_review_threshold_report(slug: str, admission: ReviewAdmission) -> str:
    """Report a review cycle's crossed threshold once, on the crossing pass only.

    Returns the empty string on every other pass. Nothing is persisted to
    derive this: the crossing pass is recomputed identically from counters
    that already exist, including after a crash-recovered orchestrator.
    """
    if not admission.crossing:
        return ""
    return _THRESHOLD_REPORT_TEMPLATE.format(
        slug=slug,
        phase=admission.phase.value,
        admitted=admission.admitted,
        threshold=admission.threshold,
        report_artifact=admission.report_artifact,
    )


def _admission_for(
    phase: ReviewPhase,
    admitted: int,
    *,
    round_offset: int = 0,
) -> ReviewAdmission:
    """Construct the next admission from the phase-owned persisted counter."""
    report_artifact = REVIEW_EVIDENCE_ARTIFACTS[phase.value].report_artifact_name
    cycle_admitted = admitted - round_offset
    candidate = cycle_admitted + 1
    return ReviewAdmission(
        phase=phase,
        admitted=cycle_admitted,
        candidate=candidate,
        threshold=DEFAULT_REVIEW_ROUND_THRESHOLD,
        cumulative_candidate=admitted + 1,
        report_artifact=report_artifact,
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
