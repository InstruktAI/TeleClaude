"""Control-delivery handoff from platform producers to agent hook boundaries."""

from __future__ import annotations

from datetime import datetime

from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.injected_text import (
    InjectedTextSourceFeature,
    TranscriptEntryKind,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import ProcessMessageCommand

IDLE_WAKE_TEXT = "[TeleClaude Notification]"


def _turn_is_running(last_input_at: datetime | None, last_stop_at: datetime | None) -> bool:
    """Use the agent-runtime turn timestamps without persisting duplicate state."""
    return last_input_at is not None and (last_stop_at is None or last_input_at > last_stop_at)


async def handoff_control_payload(*, session_id: str, body: str, source_key: str) -> int:
    """Persist exact control text, waking only an idle session with a payload-free trigger."""
    row_id, _ = await db.record_control_payload(session_id=session_id, body=body, source_key=source_key)
    session = await db.get_session(session_id)
    if session is None or _turn_is_running(session.last_message_sent_at, session.last_agent_stop_at):
        return row_id

    wake_key = f"control-delivery:{row_id}"
    await get_command_service().process_message(
        ProcessMessageCommand(
            session_id=session_id,
            text=IDLE_WAKE_TEXT,
            origin=InputOrigin.TERMINAL.value,
            text_kind=TranscriptEntryKind.PLATFORM_CONTROL,
            source_feature=InjectedTextSourceFeature.LISTENER,
            occurrence_key=wake_key,
            source_message_id=wake_key,
            actor_name="system",
        )
    )
    return row_id
