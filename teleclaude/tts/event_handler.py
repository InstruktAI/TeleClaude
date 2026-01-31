"""TTS event handler - subscribes to internal events and triggers TTS."""

from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    AgentStopPayload,
    EventContext,
    EventType,
    TeleClaudeEvents,
)
from teleclaude.tts.manager import TTSManager

# Module-level manager instance (initialized once)
_tts_manager: TTSManager | None = None


def get_tts_manager() -> TTSManager:
    """Get or create TTSManager singleton."""
    global _tts_manager  # noqa: PLW0603 - singleton pattern
    if _tts_manager is None:
        _tts_manager = TTSManager()
    return _tts_manager


async def _handle_agent_event(_event: EventType, _context: EventContext) -> None:
    """Handle agent_event → speak session start + agent stop feedback."""
    if not isinstance(_context, AgentEventContext):
        return

    manager = get_tts_manager()
    if _context.event_type == AgentHookEvents.AGENT_SESSION_START:
        await manager.trigger_event(AgentHookEvents.AGENT_SESSION_START, _context.session_id)
        return

    if _context.event_type != AgentHookEvents.AGENT_STOP:
        return

    payload = _context.data
    if not isinstance(payload, AgentStopPayload):
        return

    if not payload.summary:
        return

    await manager.trigger_event(AgentHookEvents.AGENT_STOP, _context.session_id, text=payload.summary)


def register_tts_handlers() -> None:
    """Register TTS handlers with the event bus."""
    event_bus.subscribe(TeleClaudeEvents.AGENT_EVENT, _handle_agent_event)
