"""Voluntary release of a caller-owned todo claim."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from teleclaude.core.db import Db
from teleclaude.core.next_machine.claim_authority import ClaimOwnership, classify_claim_ownership
from teleclaude.core.next_machine.driver_admission import schedule_claim_release
from teleclaude.core.next_machine.runtime.sessions import claim_is_held, is_github_backed
from teleclaude.core.next_machine.session_hold import emit_todo_updated
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.types.state_value import StateValue

_TODO_NOT_FOUND_MESSAGE = "error: todo {slug!r} was not found"
_CONFLICTING_BINDING_MESSAGE = (
    "error: cannot unclaim {slug}: caller session {caller_session_id} owns working_slug={caller_working_slug}"
)
_FOREIGN_CLAIM_MESSAGE = "error: cannot unclaim {slug}: live claim is held by session {live_claimant}"
_NO_OWNED_LIVE_CLAIM_MESSAGE = "unclaimed {slug}: no owned live claim"
_CLEARED_CLAIM_MESSAGE = "unclaimed {slug}: cleared {cleared_claims}"
_MISSING_CALLER_LABEL = "<none>"
_ACTIVE_RUNNER_FIELD = "active_runner"
_WORKING_SLUG_FIELD = "working_slug"
_CONFLICTING_BINDING_CONTEXT_MISSING = "conflicting claim binding is missing its caller context"
_FOREIGN_CLAIM_CONTEXT_MISSING = "foreign claim refusal is missing its live claimant"


class ClaimReleaseStatus(StrEnum):
    """Result category for a caller-scoped lifecycle-claim release."""

    RELEASED = "released"
    NOOP = "noop"
    REFUSED = "refused"


class ClaimReleaseReason(StrEnum):
    """Closed set of reasons a caller-scoped claim release can be refused."""

    TODO_NOT_FOUND = "todo_not_found"
    CONFLICTING_BINDING = "conflicting_binding"
    FOREIGN_CLAIM = "foreign_claim"


class ClaimReleaseFields(StrEnum):
    """Valid non-empty sets of claim fields cleared by one release."""

    ACTIVE_RUNNER = _ACTIVE_RUNNER_FIELD
    WORKING_SLUG = _WORKING_SLUG_FIELD
    ACTIVE_RUNNER_AND_WORKING_SLUG = "active_runner, working_slug"


class _ClaimReleaseOutcome(ABC):
    """Typed result describing one valid caller-scoped claim release outcome."""

    @property
    @abstractmethod
    def status(self) -> ClaimReleaseStatus: ...

    @property
    def cleared_active_runner(self) -> bool:
        return False

    @property
    def cleared_working_slug(self) -> bool:
        return False

    @property
    def refusal_reason(self) -> ClaimReleaseReason | None:
        return None


@dataclass(frozen=True)
class ClaimReleaseNoop(_ClaimReleaseOutcome):
    """A successful release request that found no caller-owned live claim."""

    slug: str

    @property
    def status(self) -> ClaimReleaseStatus:
        return ClaimReleaseStatus.NOOP


@dataclass(frozen=True)
class ClaimReleased(_ClaimReleaseOutcome):
    """A successful release of one valid non-empty set of claim fields."""

    slug: str
    fields: ClaimReleaseFields

    @property
    def status(self) -> ClaimReleaseStatus:
        return ClaimReleaseStatus.RELEASED

    @property
    def cleared_active_runner(self) -> bool:
        return self.fields in (
            ClaimReleaseFields.ACTIVE_RUNNER,
            ClaimReleaseFields.ACTIVE_RUNNER_AND_WORKING_SLUG,
        )

    @property
    def cleared_working_slug(self) -> bool:
        return self.fields in (
            ClaimReleaseFields.WORKING_SLUG,
            ClaimReleaseFields.ACTIVE_RUNNER_AND_WORKING_SLUG,
        )


class ClaimReleaseRefusal(_ClaimReleaseOutcome, ABC):
    """Base class for typed refusal outcomes."""

    @property
    def status(self) -> ClaimReleaseStatus:
        return ClaimReleaseStatus.REFUSED

    @property
    @abstractmethod
    def refusal_reason(self) -> ClaimReleaseReason: ...


@dataclass(frozen=True)
class ClaimReleaseTodoNotFound(ClaimReleaseRefusal):
    """The requested todo does not exist."""

    slug: str

    @property
    def refusal_reason(self) -> ClaimReleaseReason:
        return ClaimReleaseReason.TODO_NOT_FOUND


@dataclass(frozen=True)
class ClaimReleaseConflictingBinding(ClaimReleaseRefusal):
    """The caller is already bound to another todo."""

    slug: str
    caller_session_id: str
    caller_working_slug: str

    @property
    def refusal_reason(self) -> ClaimReleaseReason:
        return ClaimReleaseReason.CONFLICTING_BINDING


@dataclass(frozen=True)
class ClaimReleaseForeignClaim(ClaimReleaseRefusal):
    """Another live session owns the requested todo claim."""

    slug: str
    live_claimant: str

    @property
    def refusal_reason(self) -> ClaimReleaseReason:
        return ClaimReleaseReason.FOREIGN_CLAIM


type ClaimReleaseOutcome = (
    ClaimReleaseNoop
    | ClaimReleased
    | ClaimReleaseTodoNotFound
    | ClaimReleaseConflictingBinding
    | ClaimReleaseForeignClaim
)


def format_claim_release_outcome(*, outcome: ClaimReleaseOutcome) -> str:
    """Preserve the established human-readable summary and refusal messages."""
    slug = outcome.slug
    if isinstance(outcome, ClaimReleaseTodoNotFound):
        return _TODO_NOT_FOUND_MESSAGE.format(slug=slug)
    if isinstance(outcome, ClaimReleaseConflictingBinding):
        return _CONFLICTING_BINDING_MESSAGE.format(
            slug=slug,
            caller_session_id=outcome.caller_session_id or _MISSING_CALLER_LABEL,
            caller_working_slug=outcome.caller_working_slug,
        )
    if isinstance(outcome, ClaimReleaseForeignClaim):
        return _FOREIGN_CLAIM_MESSAGE.format(slug=slug, live_claimant=outcome.live_claimant)
    if isinstance(outcome, ClaimReleaseNoop):
        return _NO_OWNED_LIVE_CLAIM_MESSAGE.format(slug=slug)
    return _CLEARED_CLAIM_MESSAGE.format(slug=slug, cleared_claims=outcome.fields.value)


async def _release_active_runner(
    todos_db: WorkflowStore,
    project_root: Path,
    slug: str,
    raw_state: dict[str, StateValue],
    claimed_session_id: str | None,
) -> None:
    """Release the caller's own claim: written here for a local store, requested of the active computer for a GitHub one.

    A GitHub-backed claim is written only on the active computer, so the release is requested of it without the
    caller waiting; a release that does not reach the active computer is cleared by the active computer's reconciliation.
    """
    if claimed_session_id is not None and is_github_backed(project_root):
        schedule_claim_release(project_root, slug, claimed_session_id)
        return
    writer = StateWriter(raw_state)
    writer.state.active_runner = None
    writer.state.manually_started = False
    await writer.commit(todos_db, slug)


async def unclaim_todo_for_caller(
    db: Db,
    *,
    slug: str,
    cwd: str,
    caller_session_id: str | None,
) -> ClaimReleaseOutcome:
    project_root = resolve_project_root(cwd)
    todos_db = await get_workflow_store(project_root)
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        return ClaimReleaseTodoNotFound(slug=slug)

    session = await db.get_session(caller_session_id) if caller_session_id else None
    caller_working_slug = session.working_slug if session is not None else None
    active_runner = raw_state.get("active_runner")
    claimed_session_id = active_runner if isinstance(active_runner, str) and active_runner else None
    live_claimant = (
        claimed_session_id
        if claimed_session_id and await claim_is_held(db, project_root, slug, claimed_session_id)
        else None
    )
    ownership = classify_claim_ownership(
        slug=slug,
        caller_working_slug=caller_working_slug,
        caller_session_id=caller_session_id,
        live_claimant=live_claimant,
    )

    if ownership is ClaimOwnership.CONFLICTING_BINDING:
        if caller_session_id is None or caller_working_slug is None:
            raise RuntimeError(_CONFLICTING_BINDING_CONTEXT_MISSING)
        return ClaimReleaseConflictingBinding(
            slug=slug,
            caller_session_id=caller_session_id,
            caller_working_slug=caller_working_slug,
        )
    if ownership is ClaimOwnership.FOREIGN_CLAIM:
        if live_claimant is None:
            raise RuntimeError(_FOREIGN_CLAIM_CONTEXT_MISSING)
        return ClaimReleaseForeignClaim(slug=slug, live_claimant=live_claimant)

    cleared_active_runner = False
    if ownership is ClaimOwnership.OWNS_CLAIM:
        await _release_active_runner(todos_db, project_root, slug, raw_state, claimed_session_id)
        cleared_active_runner = True

    cleared_working_slug = False
    if ownership is ClaimOwnership.OWNS_BINDING and caller_session_id is not None:
        await db.update_session(caller_session_id, working_slug=None)
        cleared_working_slug = True
        if claimed_session_id == caller_session_id:
            await _release_active_runner(todos_db, project_root, slug, raw_state, claimed_session_id)
            cleared_active_runner = True

    if cleared_active_runner or cleared_working_slug:
        await emit_todo_updated(slug=slug, project_root=str(project_root), source="workflow.unclaim")
    if not cleared_active_runner and not cleared_working_slug:
        return ClaimReleaseNoop(slug=slug)
    if cleared_active_runner and cleared_working_slug:
        fields = ClaimReleaseFields.ACTIVE_RUNNER_AND_WORKING_SLUG
    elif cleared_active_runner:
        fields = ClaimReleaseFields.ACTIVE_RUNNER
    else:
        fields = ClaimReleaseFields.WORKING_SLUG
    return ClaimReleased(slug=slug, fields=fields)


__all__ = [
    "ClaimReleaseConflictingBinding",
    "ClaimReleaseFields",
    "ClaimReleaseForeignClaim",
    "ClaimReleaseNoop",
    "ClaimReleaseOutcome",
    "ClaimReleaseReason",
    "ClaimReleaseRefusal",
    "ClaimReleaseStatus",
    "ClaimReleaseTodoNotFound",
    "ClaimReleased",
    "format_claim_release_outcome",
    "unclaim_todo_for_caller",
]
