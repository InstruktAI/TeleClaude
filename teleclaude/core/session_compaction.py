"""Own the temporary compaction attempt recorded on a conversation session."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db import db
from teleclaude.core.models import Session
from teleclaude.core.session_revival import revive_session
from teleclaude.core.session_runtime_gate import (
    clear_relaunch_awaiting_readiness,
    mark_relaunch_awaiting_readiness,
    relaunch_awaiting_readiness,
    session_runtime_owner,
)
from teleclaude.runtime.environment import CompactionLaunchContext

_ATTEMPT_SECTION = "conversation_compaction_attempt"
_ATTEMPT_ID = "attempt_id"
_NATIVE_SESSION_ID = "native_session_id"
_STAGE = "stage"
_ATTEMPTED_AT = "attempted_at"
_MALFORMED_ATTEMPT = "Stored conversation compaction attempt is malformed"
_ATTEMPT_ALREADY_ACTIVE = "Conversation compaction attempt is already active"
_ATTEMPT_STAGE_TRANSITION_INVALID = "Conversation compaction attempt stage transition is invalid"


class CompactionStage(StrEnum):
    """Closed runtime stages for a conversation's active maintenance attempt."""

    STARTING = "starting"
    RUNNING = "running"
    RESTORING = "restoring"


@dataclass(frozen=True)
class CompactionAttempt:
    """The durable identity and current stage of one temporary launch."""

    attempt_id: str
    native_session_id: str
    stage: CompactionStage
    attempted_at: datetime


def active_compaction_attempt(session: Session) -> CompactionAttempt | None:
    """Read the active attempt from the session's platform-owned metadata."""
    metadata = session.get_origin_section(_ATTEMPT_SECTION)
    if not metadata:
        return None
    attempt_id = metadata.get(_ATTEMPT_ID)
    native_session_id = metadata.get(_NATIVE_SESSION_ID)
    stage_value = metadata.get(_STAGE)
    attempted_at_value = metadata.get(_ATTEMPTED_AT)
    if not isinstance(attempt_id, str) or not isinstance(native_session_id, str):
        raise ValueError(_MALFORMED_ATTEMPT)
    if not isinstance(stage_value, str) or not isinstance(attempted_at_value, str):
        raise ValueError(_MALFORMED_ATTEMPT)
    try:
        stage = CompactionStage(stage_value)
        attempted_at = parse_iso_datetime(attempted_at_value)
    except (ValueError, TypeError) as exc:
        raise ValueError(_MALFORMED_ATTEMPT) from exc
    if not isinstance(attempted_at, datetime):
        raise ValueError(_MALFORMED_ATTEMPT)
    return CompactionAttempt(
        attempt_id=attempt_id,
        native_session_id=native_session_id,
        stage=stage,
        attempted_at=attempted_at,
    )


def launch_context_for_attempt(attempt: CompactionAttempt) -> CompactionLaunchContext:
    """Project the persisted attempt identity into its immutable child context."""
    return CompactionLaunchContext(
        attempt_id=attempt.attempt_id,
        native_session_id=attempt.native_session_id,
    )


def last_input_at(session: Session) -> datetime | None:
    """Return the idle clock anchor: last accepted input or session creation."""
    return session.last_message_sent_at or session.created_at


def is_current_compaction_launch(session: Session, context: CompactionLaunchContext) -> bool:
    """Whether a hook belongs to the currently active attempt and native transcript."""
    attempt = active_compaction_attempt(session)
    return (
        attempt is not None
        and attempt.stage is not CompactionStage.RESTORING
        and attempt.attempt_id == context.attempt_id
        and attempt.native_session_id == context.native_session_id
        and session.native_session_id == context.native_session_id
    )


async def begin_compaction_attempt(session: Session, native_session_id: str) -> CompactionAttempt:
    """Persist a new starting attempt before its runtime is replaced.

    The caller holds the session runtime owner across this write and launch
    setup, so a second local mutation cannot begin from the same snapshot.
    """
    if active_compaction_attempt(session) is not None:
        raise RuntimeError(_ATTEMPT_ALREADY_ACTIVE)
    attempt = CompactionAttempt(
        attempt_id=str(uuid4()),
        native_session_id=native_session_id,
        stage=CompactionStage.STARTING,
        attempted_at=datetime.now(UTC),
    )
    await db.update_origin_metadata(
        session.session_id,
        _ATTEMPT_SECTION,
        {
            _ATTEMPT_ID: attempt.attempt_id,
            _NATIVE_SESSION_ID: attempt.native_session_id,
            _STAGE: attempt.stage.value,
            _ATTEMPTED_AT: attempt.attempted_at.isoformat(),
        },
    )
    return attempt


async def transition_compaction_attempt(
    session: Session,
    attempt_id: str,
    stage: CompactionStage,
) -> CompactionAttempt | None:
    """Advance the matching active attempt, ignoring stale attempt identities."""
    active = active_compaction_attempt(session)
    if active is None or active.attempt_id != attempt_id:
        return None
    if active.stage is stage:
        return active
    if active.stage is CompactionStage.STARTING and stage in {CompactionStage.RUNNING, CompactionStage.RESTORING}:
        pass
    elif active.stage is CompactionStage.RUNNING and stage is CompactionStage.RESTORING:
        pass
    else:
        raise ValueError(_ATTEMPT_STAGE_TRANSITION_INVALID)
    updated = replace(active, stage=stage)
    await db.update_origin_metadata(session.session_id, _ATTEMPT_SECTION, {_STAGE: stage.value})
    return updated


async def begin_compaction_return(session: Session, attempt_id: str) -> CompactionAttempt | None:
    """Mark a matching attempt as restoring before ordinary conversation revival."""
    async with session_runtime_owner(session.session_id):
        current = await db.get_session(session.session_id)
        if current is None:
            return None
        active = active_compaction_attempt(current)
        if active is None or active.attempt_id != attempt_id or active.stage is CompactionStage.RESTORING:
            return None
        restoring = await transition_compaction_attempt(current, attempt_id, CompactionStage.RESTORING)
        if restoring is not None:
            mark_relaunch_awaiting_readiness(session.session_id)
        return restoring


async def record_compaction_completion(session: Session, context: CompactionLaunchContext) -> bool:
    """Record provider-confirmed compaction for the matching active launch."""
    async with session_runtime_owner(session.session_id):
        current = await db.get_session(session.session_id)
        if current is None or not is_current_compaction_launch(current, context):
            return False
        attempt = active_compaction_attempt(current)
        if attempt is None:
            return False
        last_input = last_input_at(current)
        if last_input is not None and last_input > attempt.attempted_at:
            return False
        await db.update_session(session.session_id, idle_compaction_completed_at=datetime.now(UTC))
        return True


async def _clear_compaction_attempt(session: Session, attempt_id: str) -> bool:
    """Clear only the matching active attempt at its terminal boundary."""
    active = active_compaction_attempt(session)
    if active is None or active.attempt_id != attempt_id:
        return False
    await db.update_origin_metadata(
        session.session_id,
        _ATTEMPT_SECTION,
        {
            _ATTEMPT_ID: None,
            _NATIVE_SESSION_ID: None,
            _STAGE: None,
            _ATTEMPTED_AT: None,
        },
    )
    return True


async def settle_compaction_attempt(session: Session, attempt_id: str) -> bool:
    """Retire a matching attempt at a terminal boundary while holding runtime ownership."""
    return await _clear_compaction_attempt(session, attempt_id)


async def restore_ordinary_conversation(session_id: str, attempt_id: str) -> bool:
    """Abandon one temporary runtime and start its ordinary profile exactly once."""
    current = await db.get_session(session_id)
    if current is None:
        return False
    active = active_compaction_attempt(current)
    if active is None or active.attempt_id != attempt_id:
        return False
    claimed_return = False
    if active.stage is not CompactionStage.RESTORING:
        claimed_return = await begin_compaction_return(current, attempt_id) is not None
    if not claimed_return:
        current = await db.get_session(session_id)
        active = active_compaction_attempt(current) if current is not None else None
        if active is None or active.attempt_id != attempt_id or active.stage is not CompactionStage.RESTORING:
            return False
        if relaunch_awaiting_readiness(session_id):
            return True
        mark_relaunch_awaiting_readiness(session_id)
    if not await revive_session(session_id):
        clear_relaunch_awaiting_readiness(session_id)
        return False
    async with session_runtime_owner(session_id):
        current = await db.get_session(session_id)
        active = active_compaction_attempt(current) if current is not None else None
        if current is None or active is None or active.attempt_id != attempt_id:
            return False
        await db.update_session(session_id, idle_compaction_completed_at=None)
        return True


class SessionCompactionOwner:
    """One runtime authority for conversation maintenance across daemon consumers."""

    def active_attempt(self, session: Session) -> CompactionAttempt | None:
        """Read the session's current attempt through the owner boundary."""
        return active_compaction_attempt(session)

    async def begin_attempt(self, session: Session, native_session_id: str) -> CompactionAttempt:
        """Persist a new maintenance attempt."""
        return await begin_compaction_attempt(session, native_session_id)

    async def transition(self, session: Session, attempt_id: str, stage: CompactionStage) -> CompactionAttempt | None:
        """Advance one matching attempt."""
        return await transition_compaction_attempt(session, attempt_id, stage)

    async def begin_return(self, session: Session, attempt_id: str) -> CompactionAttempt | None:
        """Claim the ordinary-runtime return path once."""
        return await begin_compaction_return(session, attempt_id)

    async def begin_return_under_owner(self, session: Session, attempt_id: str) -> CompactionAttempt | None:
        """Mark a return while the caller already holds the session runtime lease."""
        active = active_compaction_attempt(session)
        if active is None or active.attempt_id != attempt_id:
            return None
        if active.stage is CompactionStage.RESTORING:
            mark_relaunch_awaiting_readiness(session.session_id)
            return active
        restoring = await transition_compaction_attempt(session, attempt_id, CompactionStage.RESTORING)
        if restoring is not None:
            mark_relaunch_awaiting_readiness(session.session_id)
        return restoring

    async def record_completion(self, session: Session, context: CompactionLaunchContext) -> bool:
        """Record only a correlated provider-confirmed compaction."""
        return await record_compaction_completion(session, context)

    async def restore_ordinary(self, session_id: str, attempt_id: str) -> bool:
        """Restore a matching attempt's ordinary runtime once."""
        return await restore_ordinary_conversation(session_id, attempt_id)

    async def settle(self, session: Session, attempt_id: str) -> bool:
        """Retire a matching attempt at a terminal boundary under its runtime lease."""
        return await settle_compaction_attempt(session, attempt_id)

    async def settle_restoring(self, session_id: str) -> bool:
        """Settle a return attempt when the ordinary runtime reaches readiness."""
        current = await db.get_session(session_id)
        return await self.settle_restoring_under_owner(current)

    async def settle_restoring_under_owner(self, session: Session | None) -> bool:
        """Settle a restoring attempt at a terminal signal or under its runtime lease."""
        if session is None:
            return False
        current = await db.get_session(session.session_id)
        active = active_compaction_attempt(current) if current is not None else None
        if current is None or active is None or active.stage is not CompactionStage.RESTORING:
            return False
        await db.update_session(current.session_id, idle_compaction_completed_at=None)
        settled = await settle_compaction_attempt(current, active.attempt_id)
        if settled:
            clear_relaunch_awaiting_readiness(current.session_id)
        return settled


session_compaction_owner = SessionCompactionOwner()
