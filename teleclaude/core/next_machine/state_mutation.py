"""State mutation boundary — the single validated write path for todo state.

Callers in API routes, lifecycle handlers, and prepare steps all persist
mutations through ``StateWriter`` (full-state validation against
:class:`TodoState`), ``ApprovalsManager`` (approval / skip / drift stamps), and
``ReviewManager`` (verdict and findings bookkeeping).

No direct :class:`WorkflowStore` writes happen outside this module in the migrated
flows — persistence is always driven by ``StateWriter``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Literal

from pydantic import ValidationError

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_PRD,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_PRD,
)
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.state_merge import apply_changes, changed_fields
from teleclaude.types.todos import (
    ApprovalsState,
    ApprovalStamp,
    AuditReviewEntry,
    AuditState,
    BuildReviewState,
    DriftReviewedStamp,
    ReviewVerdictState,
    SkipStamp,
    TodoState,
)

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore
    from teleclaude.core.workflow_store.types import ItemChange


__all__ = [
    "ApprovalsManager",
    "ReviewManager",
    "StateMutationError",
    "StateWriter",
]

_DRIFT_REVIEW_CASCADE: dict[str, tuple[str, ...]] = {
    ARTIFACT_PRD: ("prd_review", "architecture_review", "plan_review"),
    STATE_KEY_PRD: ("prd_review", "architecture_review", "plan_review"),
    ARTIFACT_ARCHITECTURE: ("architecture_review", "plan_review"),
    STATE_KEY_ARCHITECTURE: ("architecture_review", "plan_review"),
    ARTIFACT_DIAGNOSIS: ("plan_review",),
    STATE_KEY_DIAGNOSIS: ("plan_review",),
    ARTIFACT_IMPLEMENTATION_PLAN: ("plan_review",),
    STATE_KEY_IMPLEMENTATION_PLAN: ("plan_review",),
}


class StateMutationError(ValueError):
    """Raised when a mutation violates the validated state contract."""


class StateConflict(StateMutationError):
    """A writer changed the claim on a row whose claim is no longer the one it read; nothing was written."""


_CLAIM_FIELD: Final = "active_runner"
_CLAIM_CONFLICT: Final = (
    "the claim changed while the write was deciding: it read the holder {read!r} and the row now records {now!r}; "
    "repeat the call against the current state"
)


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
    return model.model_dump(exclude_none=True)


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
        self._baseline = _dump_state(self._model)

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

    def verdict_target(self, review_type: str) -> ReviewVerdictState | BuildReviewState:
        """Return the verdict-bearing sub-state for stamping verdicts."""
        review = getattr(self._model, review_type, None)
        if not isinstance(review, ReviewVerdictState | BuildReviewState):
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

    def _merged_onto(self, stored: dict[str, StateValue], final: dict[str, StateValue]) -> dict[str, StateValue]:
        """The stored state with this writer\'s changed fields applied.

        A change of the claim holder is applied only to the holder the writer read: a writer that releases or moves a
        claim it no longer holds would otherwise clear the claim of the session that took it since, so it is refused.
        """
        changes = changed_fields(self._baseline, final)
        if any(change.path == (_CLAIM_FIELD,) for change in changes):
            read_holder = self._baseline.get(_CLAIM_FIELD) or None
            stored_holder = stored.get(_CLAIM_FIELD) or None
            if read_holder != stored_holder:
                raise StateConflict(_CLAIM_CONFLICT.format(read=read_holder, now=stored_holder))
        return _dump_state(_validate_full_state(apply_changes(stored, changes)))

    async def commit(
        self,
        todos_db: WorkflowStore,
        slug: str,
    ) -> dict[str, StateValue]:
        """Validate the state and persist what this writer changed, merged onto the row the commit reads.

        Only the fields that differ from the state this writer was built from are written, in one transaction that
        reads the stored state, so a field another writer committed in between is kept, not overwritten.
        """
        from teleclaude.core.workflow_store.types import ItemChange  # noqa: PLC0415 - the store types read this package

        final = self.to_dict()
        merged: list[dict[str, StateValue]] = []

        def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
            if current is None:
                merged.append(final)
                return ItemChange(state=final)
            combined = self._merged_onto(current, final)
            merged.append(combined)
            return ItemChange(state=combined) if combined != current else None

        await todos_db.commit_item_change(slug, expect_digests={}, mutate=mutate, updated_by=None)
        return merged[-1]

    async def commit_by_id(
        self,
        todos_db: WorkflowStore,
        todo_id: str,
    ) -> dict[str, StateValue]:
        """Validate and persist the current state by durable todo row id."""
        payload = self.to_dict()
        await todos_db.write_state_by_id(todo_id, payload)
        return payload

    def commit_sync(self, todos_db: WorkflowStore, slug: str) -> dict[str, StateValue]:
        """Validate the state and persist what this writer changed, merged onto the stored row inside the transaction."""
        final = self.to_dict()
        merged: list[dict[str, StateValue]] = []

        def merge(stored: dict[str, StateValue]) -> dict[str, StateValue]:
            combined = self._merged_onto(stored, final)
            merged.append(combined)
            return combined

        todos_db.write_state_sync(slug, final, merge=merge)
        return merged[-1] if merged else final


async def commit_on_current(
    todos_db: WorkflowStore,
    slug: str,
    change: Callable[[StateWriter], None],
    *,
    updated_by: str | None = None,
) -> TodoState:
    """Apply ``change`` to the item's state as the write's own transaction reads it, and persist the result.

    The previous machine's writers read the state, mutated it and wrote the whole of it back, so a claim, a hold or a
    phase that landed in between was overwritten. This reads and writes in one row transaction under the writer lock:
    ``change`` sees the state as it is now, may raise to write nothing, and every field it does not touch is carried.
    """
    from teleclaude.core.workflow_store.types import ItemChange  # noqa: PLC0415 - the store types read this package

    outcome: list[TodoState] = []

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            raise StateMutationError(f"slug {slug!r} not found in todo list")
        writer = StateWriter(current)
        change(writer)
        outcome.append(writer.state.model_copy(deep=True))
        return ItemChange(state=writer.to_dict())

    await todos_db.commit_item_change(slug, expect_digests={}, mutate=mutate, updated_by=updated_by)
    return outcome[-1]


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
        dependency_digests_at_review: dict[str, dict[str, str]] | None = None,
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
            dependency_digests_at_review=dependency_digests_at_review or {},
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
            review.open_new_cycle()
            review.verdict = ""
            review.reviewed_at = ""
            review.reviewed_target_digest = ""
            review.review_report_digest = ""
            review.caller_session_id = ""
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

    def stamp_verdict(
        self,
        review_type: str,
        verdict: str,
        *,
        reviewed_target_digest: str,
        review_report_digest: str,
        caller_session_id: str,
    ) -> None:
        """Stamp verdict on both the visible review state and the audit entry."""
        if not reviewed_target_digest:
            raise StateMutationError("review verdict requires a reviewed target digest")
        if not review_report_digest:
            raise StateMutationError("review verdict requires a review report digest")
        if not caller_session_id:
            raise StateMutationError("review verdict requires a caller session id")
        review = self._writer.verdict_target(review_type)
        review.verdict = verdict
        now = datetime.now(UTC).isoformat()
        review.reviewed_at = now
        review.reviewed_target_digest = reviewed_target_digest
        review.review_report_digest = review_report_digest
        review.caller_session_id = caller_session_id

        if isinstance(review, ReviewVerdictState):
            audit_entry = self._writer.audit_entry(review_type)
            audit_entry.verdict = verdict
            audit_entry.completed_at = now
