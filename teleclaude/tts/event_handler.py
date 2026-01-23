"""TTS event handler - subscribes to internal events and triggers TTS."""

from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    AgentStopPayload,
    EventContext,
    EventType,
    SessionLifecycleContext,
    SessionUpdatedContext,
    TeleClaudeEvents,
)
from teleclaude.core.feedback import get_last_feedback
from teleclaude.tts.manager import TTSManager

# Module-level manager instance (initialized once)
_tts_manager: TTSManager | None = None


def get_tts_manager() -> TTSManager:
    """Get or create TTSManager singleton."""
    global _tts_manager  # noqa: PLW0603 - singleton pattern
    if _tts_manager is None:
        _tts_manager = TTSManager()
    return _tts_manager


async def _handle_session_started(event: EventType, context: EventContext) -> None:
    """Handle session_started event → speak startup greeting."""
    if not isinstance(context, SessionLifecycleContext):
        return

    manager = get_tts_manager()
    await manager.trigger_event("session_start", context.session_id)


async def _handle_agent_event(event: EventType, context: EventContext) -> None:
    """Handle agent_event → speak summary on stop."""
    if not isinstance(context, AgentEventContext):
        return

    # Only handle stop events
    if context.event_type != AgentHookEvents.AGENT_STOP:
        return

    # Get summary from payload
    if not isinstance(context.data, AgentStopPayload):
        return

    summary = context.data.summary
    if not summary:
        return

    manager = get_tts_manager()
    await manager.trigger_event("agent_stop", context.session_id, text=summary)


async def _handle_session_updated(event: EventType, context: EventContext) -> None:
    """Handle session_updated event → speak feedback when last_feedback fields change.

    This is a fallback for when feedback arrives via SESSION_UPDATED instead of AGENT_EVENT.
    Uses get_last_feedback helper to respect summarizer config.
    """
    if not isinstance(context, SessionUpdatedContext):
        return

    # Check if feedback fields were updated (either raw or summary)
    has_feedback_update = (
        "last_feedback_received" in context.updated_fields or "last_feedback_summary" in context.updated_fields
    )
    if not has_feedback_update:
        return

    # Fetch session to use the helper (respects summarizer config)
    session = await db.get_session(context.session_id)
    if not session:
        return

    feedback = get_last_feedback(session)
    if not feedback:
        return

    manager = get_tts_manager()
    await manager.trigger_event("agent_stop", context.session_id, text=feedback)


def register_tts_handlers() -> None:
    """Register TTS handlers with the event bus."""
    event_bus.subscribe(TeleClaudeEvents.SESSION_STARTED, _handle_session_started)
    event_bus.subscribe(TeleClaudeEvents.AGENT_EVENT, _handle_agent_event)
    # SESSION_UPDATED fallback for summary
    event_bus.subscribe(TeleClaudeEvents.SESSION_UPDATED, _handle_session_updated)
