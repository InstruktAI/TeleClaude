"""State mutation boundary — the single validated write path for todo state.

Callers in API routes, lifecycle handlers, and prepare steps all persist
mutations through ``StateWriter`` (full-state validation against
:class:`TodoState`), ``ApprovalsManager`` (approval / skip / drift stamps), and
``ReviewManager`` (verdict and findings bookkeeping).

No direct :class:`TodosDb` writes happen outside this module in the migrated
flows — persistence is always driven by ``StateWriter``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import ValidationError

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_PRD,
    ARTIFACT_REQUIREMENTS,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_PRD,
    STATE_KEY_REQUIREMENTS,
)
from teleclaude.core.next_machine._types import StateValue
from teleclaude.types.todos import (
    ApprovalsState,
    ApprovalStamp,
    AuditReviewEntry,
    AuditState,
    DriftReviewedStamp,
    ReviewVerdictState,
    SkipStamp,
    TodoState,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

    from teleclaude.core.todos_db import TodosDb


__all__ = [
    "ApprovalsManager",
    "ReviewManager",
    "StateMutationError",
    "StateWriter",
]

_DRIFT_REVIEW_CASCADE: dict[str, tuple[str, ...]] = {
    ARTIFACT_PRD: ("architecture_review", "plan_review"),
    STATE_KEY_PRD: ("architecture_review", "plan_review"),
    ARTIFACT_REQUIREMENTS: ("requirements_review",),
    STATE_KEY_REQUIREMENTS: ("requirements_review",),
    ARTIFACT_ARCHITECTURE: ("architecture_review", "plan_review"),
    STATE_KEY_ARCHITECTURE: ("architecture_review", "plan_review"),
    ARTIFACT_DIAGNOSIS: ("plan_review",),
    STATE_KEY_DIAGNOSIS: ("plan_review",),
    ARTIFACT_IMPLEMENTATION_PLAN: ("plan_review",),
    STATE_KEY_IMPLEMENTATION_PLAN: ("plan_review",),
}


class StateMutationError(ValueError):
    """Raised when a mutation violates the validated state contract."""


def _validate_full_state(state: dict[str, StateValue]) -> TodoState:
    """Validate the full state shape against :class:`TodoState` and return it.

    Fails fast with :class:`StateMutationError` so callers can bubble the
    rejection up to the API surface without persisting any partial mutation.
    """
    try:
        return TodoState.model_validate(state)
    except ValidationError as exc:
        raise StateMutationError(f"invalid todo state: {exc}") from exc


def _dump_state(model: TodoState) -> dict[str, StateValue]:
    """Return a JSON-safe dict for persistence."""
    payload = model.model_dump(exclude_none=True)
    if model.kind is None:
        payload["kind"] = None
    return payload


class StateWriter:
    """Validated persistence boundary for a single mutation flow.

    Callers load the current state once, mutate the typed model in-place
    through the lifecycle managers, and call :meth:`commit` (async) or
    :meth:`commit_sync` to persist. The writer re-validates the full state
    immediately before the final write so malformed persisted sub-state is
    rejected before any DB update.
    """

    def __init__(self, raw_state: dict[str, StateValue]) -> None:
        self._model = _validate_full_state(raw_state)

    @property
    def state(self) -> TodoState:
        """The typed, mutable :class:`TodoState` model under edit."""
        return self._model

    @property
    def approvals(self) -> ApprovalsState:
        """Typed prepare approval sub-state (always non-None after validation)."""
        return self._model.approvals

    @property
    def audit(self) -> AuditState:
        """Typed audit sub-state (always non-None after validation)."""
        return self._model.audit

    def review(self, review_type: str) -> ReviewVerdictState:
        """Return a `ReviewVerdictState` sub-state by phase name.

        Raises :class:`StateMutationError` for unknown phases.
        """
        review = getattr(self._model, review_type, None)
        if not isinstance(review, ReviewVerdictState):
            raise StateMutationError(f"unknown review phase: {review_type!r}")
        return review

    def verdict_target(self, review_type: str) -> ReviewVerdictState:
        """Return the verdict-bearing sub-state for stamping verdicts."""
        review = getattr(self._model, review_type, None)
        if not isinstance(review, ReviewVerdictState):
            raise StateMutationError(f"unknown review phase: {review_type!r}")
        return review

    def audit_entry(self, phase_name: str) -> AuditReviewEntry:
        """Return a typed audit review entry by phase name.

        Raises :class:`StateMutationError` for unknown phases.
        """
        entry = getattr(self._model.audit, phase_name, None)
        if not isinstance(entry, AuditReviewEntry):
            raise StateMutationError(f"unknown audit review phase: {phase_name!r}")
        return entry

    def to_dict(self) -> dict[str, StateValue]:
        """Return the current typed state as a validated dict, without persisting."""
        validated = _validate_full_state(_dump_state(self._model))
        return _dump_state(validated)

    async def commit(
        self,
        todos_db: TodosDb,
        slug: str,
        *,
        session: SqlAsyncSession | None = None,
    ) -> dict[str, StateValue]:
        """Validate and persist the current state via the async DB session.

        When ``session`` is provided the write participates in that caller-owned
        transaction, so transactional flows (e.g. ``todo_content_create``) can
        keep state persistence on the single validated boundary without opening a
        nested session.
        """
        payload = self.to_dict()
        if session is None:
            await todos_db.write_state(slug, payload)
        else:
            await todos_db.write_state(slug, payload, session=session)
        return payload

    async def commit_by_id(
        self,
        todos_db: TodosDb,
        todo_id: str,
        *,
        session: SqlAsyncSession | None = None,
    ) -> dict[str, StateValue]:
        """Validate and persist the current state by durable todo row id."""
        payload = self.to_dict()
        await todos_db.write_state_by_id(todo_id, payload, session=session)
        return payload

    def commit_sync(self, todos_db: TodosDb, slug: str) -> dict[str, StateValue]:
        """Validate and persist the current state via the sync DB path."""
        payload = self.to_dict()
        todos_db.write_state_sync(slug, payload)
        return payload


class ApprovalsManager:
    """Typed owner for prepare approval, skip, and drift review stamps."""

    def __init__(self, writer: StateWriter) -> None:
        self._writer = writer

    @property
    def state(self) -> ApprovalsState:
        """Typed approvals state under edit."""
        return self._writer.approvals

    def approve(self, field_name: str, *, caller_session_id: str, approved_digest: str = "") -> None:
        """Stamp a human approval field by name."""
        now = datetime.now(UTC).isoformat()
        setattr(
            self.state,
            field_name,
            ApprovalStamp(
                approved=True,
                approved_at=now,
                caller_session_id=caller_session_id,
                approved_digest=approved_digest,
            ),
        )

    def skip(self, field_name: str, *, reason: str, caller_session_id: str) -> None:
        """Stamp an optional prepare phase as skipped with a reason."""
        self._require_reason(field_name, reason)
        setattr(
            self.state,
            field_name,
            SkipStamp(
                reason=reason,
                skipped_at=datetime.now(UTC).isoformat(),
                caller_session_id=caller_session_id,
            ),
        )

    def drift_reviewed(
        self,
        *,
        artifact: str,
        verdict: str,
        reason: str,
        caller_session_id: str,
        head_sha_at_review: str = "",
        upstream_digests_at_review: dict[str, str] | None = None,
        snippet_digests_at_review: dict[str, str] | None = None,
    ) -> None:
        """Record drift review for one artifact."""
        if verdict not in ("substantive", "cosmetic"):
            raise StateMutationError("drift_reviewed verdict must be 'substantive' or 'cosmetic'")
        if not artifact:
            raise StateMutationError("drift_reviewed requires an artifact name")
        typed_verdict: Literal["substantive", "cosmetic"] = "substantive" if verdict == "substantive" else "cosmetic"
        self.state.drift_reviewed[artifact] = DriftReviewedStamp(
            verdict=typed_verdict,
            reason=reason,
            stamped_at=datetime.now(UTC).isoformat(),
            caller_session_id=caller_session_id,
            head_sha_at_review=head_sha_at_review,
            upstream_digests_at_review=upstream_digests_at_review or {},
            snippet_digests_at_review=snippet_digests_at_review or {},
        )
        if typed_verdict == "substantive":
            self.cascade_substantive_drift(artifact)

    def cascade_substantive_drift(self, artifact: str) -> None:
        """Clear the review verdicts an upstream artifact's substantive drift invalidates.

        Marks each cascaded review ``cleared_by_substantive_drift`` so phase
        derivation re-opens it (e.g. the implementation-plan derives back to
        ``plan_drafting``). Shared by the drift-reviewed stamp and the kickback stamp.
        """
        for review_field in _DRIFT_REVIEW_CASCADE.get(artifact, ()):
            review = self._writer.review(review_field)
            review.verdict = ""
            review.reviewed_at = ""
            review.approved_digest = ""
            review.cleared_by_substantive_drift = True
            audit = self._writer.audit_entry(review_field)
            audit.verdict = ""
            audit.completed_at = ""

    @staticmethod
    def _require_reason(field_name: str, reason: str) -> None:
        if not reason.strip():
            raise StateMutationError(f"{field_name} requires a non-empty reason")


class ReviewManager:
    """Typed review verdict owner.

    Keeps phase verdict and audit verdict aligned so they cannot diverge.
    """

    def __init__(self, writer: StateWriter) -> None:
        self._writer = writer

    def stamp_verdict(self, review_type: str, verdict: str) -> None:
        """Stamp verdict on both the visible review state and the audit entry."""
        review = self._writer.verdict_target(review_type)
        review.verdict = verdict
        now = datetime.now(UTC).isoformat()
        review.reviewed_at = now

        audit_entry = self._writer.audit_entry(review_type)
        audit_entry.verdict = verdict
        audit_entry.completed_at = now
