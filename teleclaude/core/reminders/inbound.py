"""Adapter from reminder firing to the existing inbound acceptance surface."""

from __future__ import annotations

from typing import TypedDict

from teleclaude.core.control_delivery import handoff_control_payload
from teleclaude.core.injected_text import EnvelopeField, EnvelopeName, semantic_envelope

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
        profile=entry.profile,
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
    del payload
    control_id = await handoff_control_payload(
        session_id=entry.session_id,
        body=composition.body,
        source_key=entry.occurrence_key,
        envelope=semantic_envelope(
            EnvelopeName.REMINDER,
            fields={EnvelopeField.SLUG: entry.slug, EnvelopeField.OCCURRENCE_KEY: entry.occurrence_key},
            body=composition.body,
        ),
    )
    return ReminderSubmissionResult(ReminderSubmissionPath.FRESH, control_id)
