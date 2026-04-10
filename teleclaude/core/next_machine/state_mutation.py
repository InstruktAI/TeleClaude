"""State mutation boundary — the single validated write path for todo state.

Callers in API routes, lifecycle handlers, prepare steps and event-driven
invalidation route all persisted mutations through ``StateWriter`` (full-state
validation against :class:`TodoState`), ``GroundingManager`` (freshness /
invalidate / refresh / clear_invalidation), and ``ReviewManager`` (verdict and
findings bookkeeping).

No direct :class:`TodosDb` writes happen outside this module in the migrated
flows — persistence is always driven by ``StateWriter``.
"""

# pylint: disable=cyclic-import  # State mutation boundary participates in existing next_machine import cycles.

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import ValidationError

from teleclaude.core.next_machine._types import StateValue
from teleclaude.types.todos import (
    AuditReviewEntry,
    AuditState,
    GroundingState,
    ReviewFinding,
    ReviewVerdictState,
    TodoState,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

    from teleclaude.core.todos_db import TodosDb


__all__ = [
    "GroundingManager",
    "ReviewManager",
    "StateMutationError",
    "StateWriter",
]


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

    @property
    def state(self) -> TodoState:
        """The typed, mutable :class:`TodoState` model under edit."""
        return self._model

    @property
    def grounding(self) -> GroundingState:
        """Typed grounding sub-state (always non-None after validation)."""
        return self._model.grounding

    @property
    def audit(self) -> AuditState:
        """Typed audit sub-state (always non-None after validation)."""
        return self._model.audit

    def review(self, review_type: str) -> ReviewVerdictState:
        """Return a typed review-verdict sub-state by phase name.

        Raises :class:`StateMutationError` for unknown phases so callers never
        mutate an ad hoc dict field by mistake.
        """
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
        transaction, so transactional flows (e.g. ``todo_split``) can keep
        parent-state persistence on the single validated boundary without
        opening a nested session.
        """
        payload = self.to_dict()
        if session is None:
            await todos_db.write_state(slug, payload)
        else:
            await todos_db.write_state(slug, payload, session=session)
        return payload

    def commit_sync(self, todos_db: TodosDb, slug: str) -> dict[str, StateValue]:
        """Validate and persist the current state via the sync DB path."""
        payload = self.to_dict()
        todos_db.write_state_sync(slug, payload)
        return payload


@dataclass(frozen=True, slots=True)
class GroundingResult:
    """Typed result returned by :meth:`GroundingManager.check`.

    ``is_stale`` encodes the freshness decision; ``changed_paths`` records the
    referenced files that actually diverged (empty for a fresh baseline).
    """

    is_stale: bool
    reason: str
    changed_paths: list[str]


class GroundingManager:
    """Typed grounding lifecycle owner: check / invalidate / refresh.

    Works directly on a :class:`StateWriter`'s typed ``GroundingState`` so the
    final commit is driven by the writer.
    """

    def __init__(self, writer: StateWriter) -> None:
        self._writer = writer

    @property
    def state(self) -> GroundingState:
        """Typed grounding state under edit."""
        return self._writer.grounding

    def check(
        self,
        *,
        current_sha: str,
        current_input_digest: str,
        changed_files: set[str] | None = None,
    ) -> GroundingResult:
        """Evaluate freshness of the stored baseline against current inputs.

        ``changed_files`` should contain the set of paths that changed between
        the stored ``base_sha`` and ``current_sha``; the manager computes the
        intersection with the tracked ``referenced_paths``.
        """
        grounding = self.state
        base_sha = grounding.base_sha
        stored_digest = grounding.input_digest
        referenced = list(grounding.referenced_paths)

        if not base_sha:
            return GroundingResult(is_stale=False, reason="", changed_paths=[])

        if not current_sha:
            return GroundingResult(is_stale=True, reason="files_changed", changed_paths=[])

        sha_changed = current_sha != base_sha
        digest_changed = bool(
            stored_digest
            and current_input_digest
            and len(stored_digest) == len(current_input_digest)
            and current_input_digest != stored_digest
        )

        changed_paths: list[str] = []
        if sha_changed and referenced and changed_files is not None:
            changed_paths = [p for p in referenced if p in changed_files]

        references_known = bool(referenced)
        paths_stale = bool(changed_paths)
        sha_fallback_stale = sha_changed and not references_known

        if digest_changed:
            return GroundingResult(is_stale=True, reason="input_updated", changed_paths=changed_paths)
        if paths_stale or sha_fallback_stale:
            return GroundingResult(is_stale=True, reason="files_changed", changed_paths=changed_paths)
        return GroundingResult(is_stale=False, reason="", changed_paths=[])

    def capture_fresh(self, *, current_sha: str, current_input_digest: str) -> None:
        """Record a fresh baseline against current HEAD and input digest."""
        now = datetime.now(UTC).isoformat()
        self.state.base_sha = current_sha
        self.state.input_digest = current_input_digest
        self.state.last_grounded_at = now
        self.state.valid = True
        self.state.invalidated_at = ""
        self.state.invalidation_reason = ""
        self.state.changed_paths = []

    def invalidate(self, *, reason: str, changed_paths: list[str]) -> None:
        """Mark the stored baseline stale with the given reason."""
        now = datetime.now(UTC).isoformat()
        self.state.valid = False
        self.state.invalidated_at = now
        self.state.invalidation_reason = reason
        self.state.changed_paths = list(changed_paths)

    def clear_invalidation(self) -> None:
        """Mark the stored baseline valid again, clearing any invalidation trace.

        Used by the stamp API when an operator explicitly re-grounds a todo
        out-of-band. Complements :meth:`invalidate` so both sides of the
        valid/invalid boundary go through the typed manager rather than ad hoc
        field assignments.
        """
        self.state.valid = True
        self.state.invalidated_at = ""
        self.state.invalidation_reason = ""
        self.state.changed_paths = []

    def refresh(self, *, current_sha: str) -> None:
        """Refresh the stored baseline to ``current_sha`` after re-grounding.

        Concrete fix for the re-grounding loop: once the re-grounding cycle
        has been dispatched, ``base_sha`` must be advanced so the next
        freshness check starts from the new commit instead of the old one.
        """
        now = datetime.now(UTC).isoformat()
        self.state.base_sha = current_sha
        self.state.last_grounded_at = now
        self.state.valid = True
        self.state.invalidated_at = ""
        self.state.invalidation_reason = ""
        self.state.changed_paths = []


class ReviewManager:
    """Typed review verdict and findings owner.

    Keeps phase verdict, audit verdict, findings order and resolution state
    aligned so they cannot diverge.
    """

    def __init__(self, writer: StateWriter) -> None:
        self._writer = writer

    def stamp_verdict(self, review_type: str, verdict: str) -> None:
        """Stamp verdict on both the visible review state and the audit entry."""
        review = self._writer.review(review_type)
        review.verdict = verdict
        now = datetime.now(UTC).isoformat()
        review.reviewed_at = now

        audit_entry = self._writer.audit_entry(review_type)
        audit_entry.verdict = verdict
        audit_entry.completed_at = now

    def record_finding(self, review_type: str, finding: dict[str, StateValue]) -> ReviewFinding:
        """Append a new finding to the review state.

        Rejects duplicate IDs — callers must supply a new stable ID or resolve
        the existing finding first. Returns the typed finding so callers can
        inspect the coerced record without re-reading the review state.
        """
        review = self._writer.review(review_type)
        new_finding = _coerce_finding(finding)
        if not new_finding.id:
            raise StateMutationError("finding record missing 'id' field")
        for existing in review.findings:
            if existing.id == new_finding.id:
                raise StateMutationError(f"finding id {new_finding.id!r} already recorded for {review_type}")
        review.findings.append(new_finding)
        review.findings_count = len(review.findings)
        return new_finding

    def resolve_finding(self, review_type: str, finding_id: str, resolution_method: str) -> ReviewFinding:
        """Mark a finding resolved. Fails fast when the ID is unknown."""
        review = self._writer.review(review_type)
        now = datetime.now(UTC).isoformat()
        for finding in review.findings:
            if finding.id == finding_id:
                finding.status = "resolved"
                finding.resolved_at = now
                finding.resolution_method = resolution_method
                return finding
        raise StateMutationError(f"cannot resolve unknown finding id {finding_id!r} in {review_type}")


def _coerce_finding(raw: dict[str, StateValue]) -> ReviewFinding:
    """Build a :class:`ReviewFinding` from a raw dict, failing fast on bad types."""
    try:
        return ReviewFinding.model_validate(raw)
    except ValidationError as exc:
        raise StateMutationError(f"invalid finding record: {exc}") from exc
