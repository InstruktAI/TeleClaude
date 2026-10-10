"""Route signals from temporary conversation compaction launches."""

from __future__ import annotations

from typing import cast

from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentDistressPayload,
    AgentEventContext,
    AgentHookEvents,
    AgentIdlePayload,
    AgentReadyContext,
    AgentSessionStartPayload,
    AgentStopPayload,
    TeleClaudeEvents,
)
from teleclaude.core.session_compaction import (
    SessionCompactionOwner,
    is_current_compaction_launch,
)
from teleclaude.core.session_compaction import (
    session_compaction_owner as default_compaction_owner,
)
from teleclaude.core.session_idle_compaction import compaction_completed
from teleclaude.events.envelope import EventVisibility


async def handle_compaction_event(
    context: AgentEventContext,
    owner: SessionCompactionOwner = default_compaction_owner,
) -> None:
    """Route a temporary launch's signals without applying visitor-turn effects."""
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
        event_bus.emit(
            TeleClaudeEvents.AGENT_READY,
            AgentReadyContext(
                session_id=context.session_id,
                compaction_launch_context=launch_context,
            ),
            visibility=EventVisibility.LOCAL,
        )
        return
    if context.event_type == AgentHookEvents.AGENT_IDLE:
        idle_payload = cast(AgentIdlePayload, context.data)
        if idle_payload.session_id is not None and idle_payload.session_id != launch_context.native_session_id:
            return
        completed = await owner.record_completion(session, launch_context)
        if not completed:
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
