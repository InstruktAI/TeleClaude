"""Route signals from temporary conversation compaction launches."""

from __future__ import annotations

from typing import cast

from instrukt_ai_logging import get_logger

from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.db import db
from teleclaude.core.events import (
    AgentDistressPayload,
    AgentEventContext,
    AgentHookEvents,
    AgentIdlePayload,
    AgentSessionStartPayload,
    AgentStopPayload,
)
from teleclaude.core.idle_close import close_completed_conversation
from teleclaude.core.models import Session
from teleclaude.core.runtime_readiness import RuntimeReadiness, RuntimeReadinessKey
from teleclaude.core.session_compaction import (
    SessionCompactionOwner,
    is_current_compaction_launch,
)
from teleclaude.core.session_compaction import (
    session_compaction_owner as default_compaction_owner,
)
from teleclaude.core.session_idle_compaction import compaction_completed
from teleclaude.core.session_runtime_gate import RuntimeMutationInProgress

logger = get_logger(__name__)

_IMMEDIATE_CLOSE_BUSY_EVENT = "compaction_immediate_close_busy"
_IMMEDIATE_CLOSE_FAILED_EVENT = "compaction_immediate_close_failed"


async def _close_after_completion(session: Session, client: AdapterClient, owner: SessionCompactionOwner) -> None:
    """Close the conversation whose compaction just completed; the idle cycle retries a close that did not happen."""
    try:
        await close_completed_conversation(session, client, owner)
    except RuntimeMutationInProgress:
        logger.info(_IMMEDIATE_CLOSE_BUSY_EVENT, session_id=session.session_id)
    except Exception as exc:
        logger.error(_IMMEDIATE_CLOSE_FAILED_EVENT, session_id=session.session_id, error=str(exc), exc_info=True)


async def handle_compaction_event(
    context: AgentEventContext,
    client: AdapterClient,
    runtime_readiness: RuntimeReadiness,
    owner: SessionCompactionOwner = default_compaction_owner,
) -> None:
    """Route a temporary launch's signals without applying visitor-turn effects.

    Confirmed compaction completion closes the conversation at once; the idle cycle remains the
    fallback when that close is called off or finds the conversation going on.
    """
    launch_context = context.compaction_launch_context
    if launch_context is None:
        return
    session = await db.get_session(context.session_id)
    if session is None or not is_current_compaction_launch(session, launch_context):
        return
    if context.event_type == AgentHookEvents.AGENT_SESSION_START:
        start_payload = cast(AgentSessionStartPayload, context.data)
        if start_payload.session_id is not None and start_payload.session_id != launch_context.native_session_id:
            return
        runtime_readiness.observe_start(RuntimeReadinessKey.compaction(context.session_id, launch_context))
        return
    if context.event_type == AgentHookEvents.AGENT_IDLE:
        idle_payload = cast(AgentIdlePayload, context.data)
        if idle_payload.session_id is not None and idle_payload.session_id != launch_context.native_session_id:
            return
        completed = await owner.record_completion(session, launch_context)
        if completed:
            await _close_after_completion(session, client, owner)
        else:
            await owner.restore_ordinary(context.session_id, launch_context.attempt_id)
        return
    if context.event_type in {
        AgentHookEvents.AGENT_STOP,
        AgentHookEvents.AGENT_BLOCKED,
        AgentHookEvents.AGENT_TURN_FAILED,
    }:
        terminal_payload = (
            cast(AgentStopPayload, context.data)
            if context.event_type == AgentHookEvents.AGENT_STOP
            else cast(AgentDistressPayload, context.data)
        )
        if terminal_payload.session_id is not None and terminal_payload.session_id != launch_context.native_session_id:
            return
        if context.event_type is not AgentHookEvents.AGENT_STOP or not compaction_completed(session):
            await owner.restore_ordinary(context.session_id, launch_context.attempt_id)
