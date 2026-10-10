"""Control-delivery handoff from platform producers to agent hook boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.inbound_errors import SessionMessageRejectedError
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
_CONTROL_DELIVERY_TURN_END_WAKE_EVENT = "control_delivery_turn_end_wake"
_CONTROL_DELIVERY_TURN_END_WAKE_REJECTED_EVENT = "control_delivery_turn_end_wake_rejected"
_WAKE_OCCURRENCE_KEY_TEMPLATE = "control-delivery:{row_id}"
_WAKE_ACTOR_NAME = "system"


class ControlDeliveryWakeDecision(StrEnum):
    """Closed wake policy vocabulary for semantic control delivery."""

    TIMESTAMP_DERIVED = "timestamp_derived"
    OBSERVED_IDLE = "observed_idle"


class TurnEndBoundary(StrEnum):
    """The recorded idle boundary after which pending control payloads are woken in."""

    AGENT_STOP = "agent_stop"
    AGENT_IDLE = "agent_idle"
    AGENT_TURN_FAILED = "agent_turn_failed"


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

    await _wake_for_payload(session_id=session_id, row_id=row_id, source_feature=wake_source_feature)
    return row_id


async def wake_if_pending(*, session_id: str, boundary: TurnEndBoundary) -> None:
    """Wake a session whose recorded turn end left a control payload pending.

    The platform records a turn end only after the runtime's last delivery
    boundary has run, so a payload handed off in between saw a running turn
    and was not woken by its producer. Called after every idle-boundary write,
    this closes that interval: the producer writes its payload then reads the
    turn state, and the turn-end recorder writes the boundary then reads the
    pending payloads, so one of the two always wakes the session.
    """
    pending = await db.get_pending_control_payloads(session_id=session_id)
    if not pending:
        return
    newest_row_id = pending[-1].id
    logger.info(
        _CONTROL_DELIVERY_TURN_END_WAKE_EVENT,
        session_id=session_id,
        boundary=boundary.value,
        pending_count=len(pending),
        wake_row_id=newest_row_id,
    )
    try:
        await _wake_for_payload(
            session_id=session_id,
            row_id=newest_row_id,
            source_feature=InjectedTextSourceFeature.LISTENER,
        )
    except SessionMessageRejectedError as exc:
        # A session that no longer accepts input is closing; its pending payloads go with it.
        # The turn-end recorder that called this still owes the rest of its transition.
        logger.info(
            _CONTROL_DELIVERY_TURN_END_WAKE_REJECTED_EVENT,
            session_id=session_id,
            boundary=boundary.value,
            wake_row_id=newest_row_id,
            reason=exc.reason.value,
        )


async def _wake_for_payload(*, session_id: str, row_id: int, source_feature: InjectedTextSourceFeature) -> None:
    """Type the content-free wake, keyed by the payload it serves so a repeat is accepted once."""
    wake_key = _WAKE_OCCURRENCE_KEY_TEMPLATE.format(row_id=row_id)
    await get_command_service().process_message(
        ProcessMessageCommand(
            session_id=session_id,
            text=IDLE_WAKE_TEXT,
            origin=InputOrigin.TERMINAL.value,
            text_kind=TranscriptEntryKind.PLATFORM_CONTROL,
            source_feature=source_feature,
            occurrence_key=wake_key,
            source_message_id=wake_key,
            actor_name=_WAKE_ACTOR_NAME,
        )
    )
