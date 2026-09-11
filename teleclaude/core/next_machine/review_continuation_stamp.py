"""The review-continuation stamp: one admitted pass past a capped review's hard limit.

Split out of ``stamps.py`` to keep that domain-boundary module under the
repository's module-size guardrail. Owns the entire authority decision for
``review_continuation`` — ``stamps._validate_stamp_authority`` returns early
for this stamp type because the shared claim classification cannot separate
the claiming orchestrator from its slug-bound workers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import JobRole
from teleclaude.core.db import db as runtime_db
from teleclaude.core.db import get_session_field_sync
from teleclaude.core.next_machine.review_evidence import REVIEW_EVIDENCE_ARTIFACTS
from teleclaude.core.next_machine.review_rounds import ReviewPhase, build_cycle_admission, prepare_cycle_admission
from teleclaude.core.next_machine.runtime.sessions import is_live_session_id
from teleclaude.core.next_machine.state_mutation import StateMutationError, StateWriter
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import (
    ReviewContinuation,
    ReviewContinuationCallerRole,
    ReviewHaltClassification,
    ReviewVerdictState,
)

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)

REVIEW_CONTINUATION_STAMP_TYPE = "review_continuation"
_REVIEW_CONTINUATION_DECIDED_EVENT = "workflow.review_continuation_stamp_decided"
_REVIEW_CONTINUATION_REFUSED_CLASSES = frozenset(
    {ReviewHaltClassification.AMBIGUOUS_CONTRACT, ReviewHaltClassification.UNSTABLE_TARGET}
)
_REVIEW_CONTINUATION_CLASSIFICATION_PHRASES: dict[str, ReviewHaltClassification] = {
    "failed remediation": ReviewHaltClassification.FAILED_REMEDIATION,
    "incomplete review": ReviewHaltClassification.INCOMPLETE_REVIEW,
    "noisy review": ReviewHaltClassification.NOISY_REVIEW,
    "ambiguous contract": ReviewHaltClassification.AMBIGUOUS_CONTRACT,
    "unstable target": ReviewHaltClassification.UNSTABLE_TARGET,
}


class ReviewContinuationRefusal(StrEnum):
    """Closed refusal-reason vocabulary for the review-continuation stamp."""

    INVALID_PHASE = "invalid_phase"
    MALFORMED_REASON = "malformed_reason"
    CLASS_EARNS_NO_CONTINUATION = "class_earns_no_continuation"
    NOT_AT_CAP = "not_at_cap"
    CALLER_NOT_CLAIMANT = "caller_not_claimant"


def _parse_review_continuation_reason(reason: str) -> tuple[ReviewHaltClassification | None, str]:
    """Split ``<classification>: <text>`` and match the closed classification vocabulary.

    Returns ``(None, "")`` when the leading classification does not match one
    of the review procedure's five halt classes, or the trailing evidence text
    is empty. The evidence text itself is stored verbatim and read only by
    intelligence; this function grades nothing about its content.
    """
    if ":" not in reason:
        return None, ""
    head, _, tail = reason.partition(":")
    text = tail.strip()
    classification = _REVIEW_CONTINUATION_CLASSIFICATION_PHRASES.get(head.strip().lower())
    if classification is None or not text:
        return None, ""
    return classification, text


_ASSESSOR_DECLARATION_PREFIX = "assessed-by "
_ASSESSOR_ROLES = {
    ReviewContinuationCallerRole.HUMAN.value: ReviewContinuationCallerRole.HUMAN,
    ReviewContinuationCallerRole.COORDINATOR.value: ReviewContinuationCallerRole.COORDINATOR,
}


def _parse_declared_assessor(evidence: str) -> tuple[ReviewContinuationCallerRole | None, str]:
    """Read the assessor role and identity a claimant declares at the head of its evidence.

    The declaration is ``assessed-by <role>:<identity>;`` in a documented
    position, read the same structural way as the classification prefix: the
    role comes from a closed vocabulary and the identity is stored verbatim.
    Whether the named assessor truly assessed is not decidable here and is
    never graded; the record makes the declaration falsifiable and the human's
    sweep audits it.
    """
    if not evidence.startswith(_ASSESSOR_DECLARATION_PREFIX):
        return None, ""
    remainder = evidence[len(_ASSESSOR_DECLARATION_PREFIX) :]
    declaration, _, _ = remainder.partition(";")
    role_token, separator, identity = declaration.partition(":")
    if not separator:
        return None, ""
    role = _ASSESSOR_ROLES.get(role_token.strip().lower())
    assessor_id = identity.strip()
    if role is None or not assessor_id:
        return None, ""
    return role, assessor_id


def _log_review_continuation_decision(
    *,
    slug: str,
    phase: str,
    ordinal: int,
    caller_role: str,
    classification: str,
    outcome: str,
    reason: ReviewContinuationRefusal | None = None,
) -> None:
    logger.info(
        _REVIEW_CONTINUATION_DECIDED_EVENT,
        slug=slug,
        phase=phase,
        ordinal=ordinal,
        caller_role=caller_role,
        classification=classification,
        outcome=outcome,
        reason=reason.value if reason is not None else "",
    )


async def apply_review_continuation_stamp(
    todos_db: TodosDb,
    writer: StateWriter,
    slug: str,
    *,
    phase: str | None,
    reason: str,
    caller_session_id: str | None,
) -> dict[str, StateValue]:
    """Record one admitted continuation past a capped review phase's hard limit.

    ``stamps._validate_stamp_authority`` returns early for this stamp type —
    the shared claim classification cannot separate the claiming orchestrator
    from its slug-bound workers, and refuses a coordinator or human principal
    before this handler could run. This function owns the entire authority
    decision by comparing caller identity against the todo's live
    ``active_runner``, per the review procedure's convergence rule (§6).
    """
    if phase is None or phase not in REVIEW_EVIDENCE_ARTIFACTS:
        _log_review_continuation_decision(
            slug=slug,
            phase=phase or "",
            ordinal=0,
            caller_role="",
            classification="",
            outcome="refused",
            reason=ReviewContinuationRefusal.INVALID_PHASE,
        )
        raise StateMutationError(f"cannot stamp review_continuation: unknown review phase {phase!r}")

    classification, evidence_text = _parse_review_continuation_reason(reason)
    if classification is None:
        _log_review_continuation_decision(
            slug=slug,
            phase=phase,
            ordinal=0,
            caller_role="",
            classification="",
            outcome="refused",
            reason=ReviewContinuationRefusal.MALFORMED_REASON,
        )
        raise StateMutationError(
            "cannot stamp review_continuation: --reason must read '<classification>: <evidence>' where "
            "classification is one of: failed remediation, incomplete review, noisy review, "
            "ambiguous contract, unstable target"
        )
    if classification in _REVIEW_CONTINUATION_REFUSED_CLASSES:
        _log_review_continuation_decision(
            slug=slug,
            phase=phase,
            ordinal=0,
            caller_role="",
            classification=classification.value,
            outcome="refused",
            reason=ReviewContinuationRefusal.CLASS_EARNS_NO_CONTINUATION,
        )
        raise StateMutationError(f"cannot stamp review_continuation: {classification.value} earns no continuation")

    review = writer.verdict_target(phase)
    if isinstance(review, ReviewVerdictState):
        admission = prepare_cycle_admission(ReviewPhase(phase), review)
        ordinal = len(review.continuations) - review.cycle.continuation_offset + 1
    else:
        admission = build_cycle_admission(review)
        ordinal = len(review.continuations) + 1
    if admission.allowed:
        _log_review_continuation_decision(
            slug=slug,
            phase=phase,
            ordinal=0,
            caller_role="",
            classification=classification.value,
            outcome="refused",
            reason=ReviewContinuationRefusal.NOT_AT_CAP,
        )
        raise StateMutationError(
            f"cannot stamp review_continuation: {phase} has not reached its current allowance "
            f"({admission.admitted}/{admission.maximum})"
        )

    active_runner = writer.state.active_runner
    assessor_role: ReviewContinuationCallerRole | None = None
    assessor_id = ""
    is_human_caller = bool(caller_session_id and caller_session_id.startswith("human:"))
    caller_role: ReviewContinuationCallerRole
    if ordinal == 1:
        if is_human_caller or not caller_session_id or caller_session_id != active_runner:
            _log_review_continuation_decision(
                slug=slug,
                phase=phase,
                ordinal=ordinal,
                caller_role="",
                classification=classification.value,
                outcome="refused",
                reason=ReviewContinuationRefusal.CALLER_NOT_CLAIMANT,
            )
            raise PermissionError(
                f"review_continuation stamp for {slug} phase {phase} at ordinal 1 requires the claiming "
                f"orchestrator session {active_runner or '<none>'}"
            )
        if not await is_live_session_id(runtime_db, caller_session_id):
            _log_review_continuation_decision(
                slug=slug,
                phase=phase,
                ordinal=ordinal,
                caller_role="",
                classification=classification.value,
                outcome="refused",
                reason=ReviewContinuationRefusal.CALLER_NOT_CLAIMANT,
            )
            raise PermissionError(
                f"review_continuation stamp for {slug} phase {phase} at ordinal 1 requires a live claiming session"
            )
        caller_role = ReviewContinuationCallerRole.CLAIMANT
    else:
        if is_human_caller:
            caller_role = ReviewContinuationCallerRole.HUMAN
        elif caller_session_id and caller_session_id == active_runner:
            assessor_role, assessor_id = _parse_declared_assessor(evidence_text)
            if assessor_role is None:
                _log_review_continuation_decision(
                    slug=slug,
                    phase=phase,
                    ordinal=ordinal,
                    caller_role="",
                    classification=classification.value,
                    outcome="refused",
                    reason=ReviewContinuationRefusal.CALLER_NOT_CLAIMANT,
                )
                raise PermissionError(
                    f"review_continuation stamp for {slug} phase {phase} at ordinal {ordinal} written by the "
                    "claiming orchestrator must declare its assessor: begin --reason evidence with "
                    "'assessed-by human:<principal>;' or 'assessed-by coordinator:<session-id>;'"
                )
            caller_role = ReviewContinuationCallerRole.CLAIMANT
        else:
            job = get_session_field_sync(str(MAIN_DB_PATH), caller_session_id, "job") if caller_session_id else None
            if job != JobRole.COORDINATOR.value:
                _log_review_continuation_decision(
                    slug=slug,
                    phase=phase,
                    ordinal=ordinal,
                    caller_role="",
                    classification=classification.value,
                    outcome="refused",
                    reason=ReviewContinuationRefusal.CALLER_NOT_CLAIMANT,
                )
                raise PermissionError(
                    f"review_continuation stamp for {slug} phase {phase} at ordinal {ordinal} requires the claiming "
                    "orchestrator session, a coordinator session, or a human principal"
                )
            caller_role = ReviewContinuationCallerRole.COORDINATOR

    if caller_role is ReviewContinuationCallerRole.CLAIMANT and ordinal > 1:
        recorded_assessor, recorded_assessor_id = assessor_role, assessor_id
    elif ordinal > 1:
        recorded_assessor, recorded_assessor_id = caller_role, caller_session_id or ""
    else:
        recorded_assessor, recorded_assessor_id = None, ""
    review.continuations.append(
        ReviewContinuation(
            assessor_role=recorded_assessor,
            assessor_id=recorded_assessor_id,
            classification=classification,
            reason=evidence_text,
            caller_session_id=caller_session_id or "",
            caller_role=caller_role,
            stamped_at=datetime.now(UTC).isoformat(),
        )
    )
    payload = await writer.commit(todos_db, slug)
    _log_review_continuation_decision(
        slug=slug,
        phase=phase,
        ordinal=ordinal,
        caller_role=caller_role.value,
        classification=classification.value,
        outcome="stamped",
    )
    return payload
