"""Adapter from reminder firing to the existing inbound acceptance surface."""

from __future__ import annotations

import json
from typing import TypedDict

from teleclaude.core.db import db
from teleclaude.core.inbound_queue import get_inbound_queue_manager
from teleclaude.core.inbound_types import InboundMessageType
from teleclaude.core.injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from teleclaude.core.origins import InputOrigin

from .models import ReminderEntry, ReminderSubmissionPath, ReminderSubmissionResult
from .observability import observe_envelope_composed
from .presentation import compose_agent_reminder


class ReminderInboundPayload(TypedDict):
    """Structured reminder identity persisted independently of presentation."""

    reminder_entry_id: int
    slug: str
    generation: int
    transition: str
    occurrence_key: str
    profile: str | None
    intent: str
    recurrence: str
    trigger_type: str
    event_anchor: str | None
    armed_at: str
    occurred_at: str
    next_fire_at: str | None


async def submit_reminder_entry(entry: ReminderEntry) -> ReminderSubmissionResult:
    """Submit a firing entry through the durable queue's acceptance boundary."""
    payload = ReminderInboundPayload(
        reminder_entry_id=entry.entry_id,
        slug=entry.slug,
        generation=entry.generation,
        transition=entry.transition.value,
        occurrence_key=entry.occurrence_key,
        profile=entry.profile.value if entry.profile is not None else None,
        intent=entry.intent,
        recurrence=entry.schedule.recurrence.value,
        trigger_type=entry.schedule.trigger.value,
        event_anchor=entry.schedule.event_anchor.value if entry.schedule.event_anchor is not None else None,
        armed_at=entry.armed_at.isoformat(),
        occurred_at=entry.occurred_at.isoformat(),
        next_fire_at=entry.schedule.next_fire_at.isoformat() if entry.schedule.next_fire_at is not None else None,
    )
    composition = compose_agent_reminder(entry)
    observe_envelope_composed(
        entry,
        explicit_noop=composition.explicit_noop,
        auto_cancel=composition.auto_cancel,
    )
    inbound_id = await get_inbound_queue_manager().enqueue(
        session_id=entry.session_id,
        origin=InputOrigin.REMINDER.value,
        content=composition.rendered,
        message_type=InboundMessageType.REMINDER.value,
        text_kind=TranscriptEntryKind.REMINDER,
        source_feature=InjectedTextSourceFeature.REMINDER,
        occurrence_key=entry.occurrence_key,
        payload_json=json.dumps(payload, sort_keys=True),
        source_message_id=entry.occurrence_key,
        notify_typing=False,
    )
    if inbound_id is not None:
        return ReminderSubmissionResult(ReminderSubmissionPath.FRESH, inbound_id)
    duplicate_id = await db.get_inbound_id_by_source(
        origin=InputOrigin.REMINDER.value,
        source_message_id=entry.occurrence_key,
    )
    if duplicate_id is not None:
        return ReminderSubmissionResult(ReminderSubmissionPath.DUPLICATE_BOUND, duplicate_id)
    return ReminderSubmissionResult(ReminderSubmissionPath.DUPLICATE_UNBOUND, None)
