"""Single owner for persisted agent-session lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from teleclaude.core.session_status import SessionLifecycleStatus

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


@dataclass(frozen=True)
class LifecycleTransition:
    """A typed lifecycle request with the evidence the state change requires."""

    target: SessionLifecycleStatus
    reason: LifecycleTransitionReason
    runtime_start_observed: bool | None = None
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
        closed_at=transition.closed_at,
    )
