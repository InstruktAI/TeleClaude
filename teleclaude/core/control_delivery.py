"""Control-delivery handoff from platform producers to agent hook boundaries."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.injected_text import (
    EnvelopeName,
    InjectedTextSourceFeature,
    SemanticEnvelope,
    TranscriptEntryKind,
    render_bracket_envelope,
    semantic_envelope,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import ProcessMessageCommand

IDLE_WAKE_TEXT = render_bracket_envelope(semantic_envelope(EnvelopeName.WAKE))


class ControlDeliveryWakeDecision(StrEnum):
    """Closed wake policy vocabulary for semantic control delivery."""

    TIMESTAMP_DERIVED = "timestamp_derived"
    OBSERVED_IDLE = "observed_idle"


def _turn_is_running(last_input_at: datetime | None, last_stop_at: datetime | None) -> bool:
    """Use the agent-runtime turn timestamps without persisting duplicate state."""
    return last_input_at is not None and (last_stop_at is None or last_input_at > last_stop_at)


async def handoff_control_payload(
    *,
    session_id: str,
    body: str,
    source_key: str,
    envelope: SemanticEnvelope | None = None,
    wake_decision: ControlDeliveryWakeDecision = ControlDeliveryWakeDecision.TIMESTAMP_DERIVED,
    wake_source_feature: InjectedTextSourceFeature = InjectedTextSourceFeature.LISTENER,
) -> int:
    """Persist semantic control facts, waking only an idle session with a payload-free trigger."""
    row_id, _ = await db.record_control_payload(
        session_id=session_id,
        body=body,
        source_key=source_key,
        envelope_name=envelope.definition.name.value if envelope is not None else None,
        envelope_fields={field.value: value for field, value in envelope.fields.items()}
        if envelope is not None
        else None,
    )
    session = await db.get_session(session_id)
    if session is None or (
        wake_decision is ControlDeliveryWakeDecision.TIMESTAMP_DERIVED
        and _turn_is_running(session.last_message_sent_at, session.last_agent_stop_at)
    ):
        return row_id

    wake_key = f"control-delivery:{row_id}"
    await get_command_service().process_message(
        ProcessMessageCommand(
            session_id=session_id,
            text=IDLE_WAKE_TEXT,
            origin=InputOrigin.TERMINAL.value,
            text_kind=TranscriptEntryKind.PLATFORM_CONTROL,
            source_feature=wake_source_feature,
            occurrence_key=wake_key,
            source_message_id=wake_key,
            actor_name="system",
        )
    )
    return row_id
