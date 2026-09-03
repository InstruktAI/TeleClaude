"""Single owner for persisted agent-session lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from teleclaude.config._models import STALL_THRESHOLD_SECONDS
from teleclaude.core.agents import AgentName
from teleclaude.core.events import AgentStopCompletionSource, AgentStopPayload
from teleclaude.core.session_status import SessionLifecycleStatus, is_session_terminal

if TYPE_CHECKING:
    from teleclaude.core.models import Session


class LifecycleTransitionReason(StrEnum):
    """Closed vocabulary describing why the lifecycle owner changed state."""

    CREATED = "created"
    RUNTIME_SESSION_START = "runtime_session_start"
    RESTART_INITIALIZED = "restart_initialized"
    ADOPTION_INITIALIZED = "adoption_initialized"
    HEADLESS_RESTORED = "headless_restored"
    ESCALATED = "escalated"
    HANDBACK = "handback"
    CLOSE_STARTED = "close_started"
    CLOSE_FAILED = "close_failed"
    CLOSED = "closed"
    MIGRATED_NATIVE_SESSION = "migrated_native_session"
    MIGRATED_UNPROVEN = "migrated_unproven"


class CodexStopRecoveryRejectionReason(StrEnum):
    """Closed reasons a delayed Codex completion cannot finalize the current turn."""

    ACCEPTED = "accepted"
    MISSING_SESSION = "missing_session"
    TERMINAL = "terminal"
    INITIALIZING = "initializing"
    NOT_CODEX = "not_codex"
    RUNTIME_NOT_STARTED = "runtime_not_started"
    MALFORMED = "malformed"
    SUPERSEDED_INPUT = "superseded_input"
    NOT_NEWER_THAN_INPUT = "not_newer_than_input"
    ALREADY_COMPLETED = "already_completed"


@dataclass(frozen=True)
class CodexStopRecoveryDecision:
    """Eligibility result for the only delayed completion recovery path."""

    accepted: bool
    reason: CodexStopRecoveryRejectionReason


@dataclass(frozen=True)
class LifecycleTransition:
    """A typed lifecycle request with the evidence the state change requires."""

    target: SessionLifecycleStatus
    reason: LifecycleTransitionReason
    runtime_start_observed: bool | None = None
    runtime_activity_at: datetime | None = None
    closed_at: datetime | None = None


class LifecycleStore(Protocol):
    """Narrow persistence seam owned by the lifecycle transition module."""

    async def get_session(self, session_id: str) -> Session | None: ...

    async def persist_lifecycle_transition(
        self,
        session_id: str,
        *,
        target: str,
        reason: str,
        transitioned_at: datetime,
        runtime_start_observed: bool | None = None,
        runtime_activity_at: datetime | None = None,
        closed_at: datetime | None = None,
    ) -> None: ...


_ALLOWED_SOURCES: dict[LifecycleTransitionReason, frozenset[SessionLifecycleStatus]] = {
    LifecycleTransitionReason.CREATED: frozenset(),
    LifecycleTransitionReason.RUNTIME_SESSION_START: frozenset(
        {SessionLifecycleStatus.INITIALIZING, SessionLifecycleStatus.ACTIVE}
    ),
    LifecycleTransitionReason.RESTART_INITIALIZED: frozenset(
        {SessionLifecycleStatus.ACTIVE, SessionLifecycleStatus.HEADLESS, SessionLifecycleStatus.CLOSED}
    ),
    LifecycleTransitionReason.ADOPTION_INITIALIZED: frozenset({SessionLifecycleStatus.HEADLESS}),
    LifecycleTransitionReason.HEADLESS_RESTORED: frozenset(
        {SessionLifecycleStatus.INITIALIZING, SessionLifecycleStatus.ACTIVE}
    ),
    LifecycleTransitionReason.ESCALATED: frozenset({SessionLifecycleStatus.ACTIVE}),
    LifecycleTransitionReason.HANDBACK: frozenset({SessionLifecycleStatus.ESCALATED}),
    LifecycleTransitionReason.CLOSE_STARTED: frozenset(
        {
            SessionLifecycleStatus.ACTIVE,
            SessionLifecycleStatus.INITIALIZING,
            SessionLifecycleStatus.HEADLESS,
            SessionLifecycleStatus.ESCALATED,
        }
    ),
    LifecycleTransitionReason.CLOSE_FAILED: frozenset({SessionLifecycleStatus.CLOSING}),
    LifecycleTransitionReason.CLOSED: frozenset(
        {
            SessionLifecycleStatus.ACTIVE,
            SessionLifecycleStatus.INITIALIZING,
            SessionLifecycleStatus.HEADLESS,
            SessionLifecycleStatus.ESCALATED,
            SessionLifecycleStatus.CLOSING,
        }
    ),
    LifecycleTransitionReason.MIGRATED_UNPROVEN: frozenset({SessionLifecycleStatus.ACTIVE}),
}


def readiness_projection(
    *, lifecycle_status: str | None, created_at: datetime | None, active_agent: str | None, now: datetime
) -> tuple[int | None, str | None, str | None]:
    """Return additive investigation facts for an unproved agent startup."""
    if lifecycle_status != SessionLifecycleStatus.INITIALIZING or not created_at or not active_agent:
        return None, None, None
    elapsed = int((now - created_at).total_seconds())
    if elapsed < STALL_THRESHOLD_SECONDS:
        return elapsed, None, None
    return elapsed, "readiness_investigation", "general/procedure/orchestration#agent-degradation-handling"


def decide_codex_stop_recovery(session: Session | None, payload: AgentStopPayload) -> CodexStopRecoveryDecision:
    """Decide whether delayed provider evidence still belongs to the current session turn."""
    if session is None:
        return CodexStopRecoveryDecision(False, CodexStopRecoveryRejectionReason.MISSING_SESSION)
    if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
        return CodexStopRecoveryDecision(False, CodexStopRecoveryRejectionReason.TERMINAL)
    if session.lifecycle_status == SessionLifecycleStatus.INITIALIZING:
        return CodexStopRecoveryDecision(False, CodexStopRecoveryRejectionReason.INITIALIZING)
    if session.active_agent != AgentName.CODEX.value:
        return CodexStopRecoveryDecision(False, CodexStopRecoveryRejectionReason.NOT_CODEX)
    if not session.runtime_start_observed:
        return CodexStopRecoveryDecision(False, CodexStopRecoveryRejectionReason.RUNTIME_NOT_STARTED)
    if (
        payload.completion_source is not AgentStopCompletionSource.CODEX_TASK_RECOVERY
        or payload.native_turn_id is None
        or payload.native_completed_at is None
        or payload.accepted_input_at is None
        or session.last_message_sent_at is None
    ):
        return CodexStopRecoveryDecision(False, CodexStopRecoveryRejectionReason.MALFORMED)
    current_input_at = _as_utc(session.last_message_sent_at)
    native_completed_at = _as_utc(payload.native_completed_at)
    accepted_input_at = _as_utc(payload.accepted_input_at)
    if current_input_at is None or native_completed_at is None or accepted_input_at is None:
        return CodexStopRecoveryDecision(False, CodexStopRecoveryRejectionReason.MALFORMED)
    if current_input_at != accepted_input_at:
        return CodexStopRecoveryDecision(False, CodexStopRecoveryRejectionReason.SUPERSEDED_INPUT)
    if native_completed_at <= current_input_at:
        return CodexStopRecoveryDecision(False, CodexStopRecoveryRejectionReason.NOT_NEWER_THAN_INPUT)
    last_stop_at = _as_utc(session.last_agent_stop_at)
    if last_stop_at is not None and last_stop_at >= native_completed_at:
        return CodexStopRecoveryDecision(False, CodexStopRecoveryRejectionReason.ALREADY_COMPLETED)
    return CodexStopRecoveryDecision(True, CodexStopRecoveryRejectionReason.ACCEPTED)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def transition_session(store: LifecycleStore, session_id: str, transition: LifecycleTransition) -> None:
    """Validate and persist one lifecycle transition through the sole write seam."""
    session = await store.get_session(session_id)
    if session is None:
        raise ValueError(f"Cannot transition missing session {session_id}")
    current = SessionLifecycleStatus(session.lifecycle_status or SessionLifecycleStatus.INITIALIZING)
    allowed = _ALLOWED_SOURCES[transition.reason]
    if transition.reason is LifecycleTransitionReason.CREATED:
        if current is not transition.target:
            raise ValueError("Creation transition must preserve the created lifecycle state")
    elif current not in allowed:
        raise ValueError(f"Lifecycle transition {transition.reason} is not allowed from {current}")
    if transition.reason is LifecycleTransitionReason.RUNTIME_SESSION_START:
        if transition.target is not SessionLifecycleStatus.ACTIVE or transition.runtime_start_observed is not True:
            raise ValueError("Runtime session start requires observed start evidence and active target")
    await store.persist_lifecycle_transition(
        session_id,
        target=transition.target.value,
        reason=transition.reason.value,
        transitioned_at=datetime.now(UTC),
        runtime_start_observed=transition.runtime_start_observed,
        runtime_activity_at=transition.runtime_activity_at,
        closed_at=transition.closed_at,
    )
