"""Control-delivery handoff from platform producers to agent hook boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.injected_text import (
    EnvelopeField,
    EnvelopeName,
    InjectedTextSourceFeature,
    SemanticEnvelope,
    TranscriptEntryKind,
    render_bracket_envelope,
    semantic_envelope,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_status import is_agent_turn_running
from teleclaude.types.commands import ProcessMessageCommand

logger = get_logger(__name__)

IDLE_WAKE_TEXT = render_bracket_envelope(semantic_envelope(EnvelopeName.WAKE))

_CONTROL_DELIVERY_PAYLOAD_SUPERSEDED_EVENT = "control_delivery_payload_superseded"


class ControlDeliveryWakeDecision(StrEnum):
    """Closed wake policy vocabulary for semantic control delivery."""

    TIMESTAMP_DERIVED = "timestamp_derived"
    OBSERVED_IDLE = "observed_idle"


@dataclass(frozen=True)
class SupersessionKey:
    """A producer's declaration that its handoff supersedes older undelivered payloads.

    ``key_fields`` identifies the older payloads sharing this handoff's
    envelope kind that a producer wants retired without delivery — for a
    recurring reminder, its slug. An empty mapping names nothing and is a
    contract violation, not a wildcard that would match every pending
    payload of the envelope kind.
    """

    envelope_name: EnvelopeName
    key_fields: Mapping[EnvelopeField, str]

    def __post_init__(self) -> None:
        if not self.key_fields:
            raise ValueError("SupersessionKey.key_fields must name at least one field")


async def handoff_control_payload(
    *,
    session_id: str,
    body: str,
    source_key: str,
    envelope: SemanticEnvelope | None = None,
    wake_decision: ControlDeliveryWakeDecision = ControlDeliveryWakeDecision.TIMESTAMP_DERIVED,
    wake_source_feature: InjectedTextSourceFeature = InjectedTextSourceFeature.LISTENER,
    supersedes: SupersessionKey | None = None,
) -> int:
    """Persist semantic control facts, waking only an idle session with a payload-free trigger.

    When ``supersedes`` is set, this payload's own older pending payloads —
    matching its envelope kind and every declared key field for this session
    — are removed without delivery once this payload is recorded, before the
    wake decision runs. ``None`` (the default) declares nothing; every prior
    payload stays pending, unchanged from before this parameter existed.
    """
    row_id, _ = await db.record_control_payload(
        session_id=session_id,
        body=body,
        source_key=source_key,
        envelope_name=envelope.definition.name.value if envelope is not None else None,
        envelope_fields={field.value: value for field, value in envelope.fields.items()}
        if envelope is not None
        else None,
    )
    if supersedes is not None:
        key_fields = {field.value: value for field, value in supersedes.key_fields.items()}
        removed_row_ids = await db.discard_superseded_control_payloads(
            session_id=session_id,
            envelope_name=supersedes.envelope_name.value,
            key_fields=key_fields,
            before_row_id=row_id,
        )
        logger.info(
            _CONTROL_DELIVERY_PAYLOAD_SUPERSEDED_EVENT,
            session_id=session_id,
            envelope_name=supersedes.envelope_name.value,
            superseding_row_id=row_id,
            removed_row_ids=removed_row_ids,
            removed_count=len(removed_row_ids),
            **key_fields,
        )
    session = await db.get_session(session_id)
    if session is None or (
        wake_decision is ControlDeliveryWakeDecision.TIMESTAMP_DERIVED
        and is_agent_turn_running(
            last_input_at=session.last_message_sent_at,
            last_agent_stop_at=session.last_agent_stop_at,
            last_agent_idle_at=session.last_agent_idle_at,
        )
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
