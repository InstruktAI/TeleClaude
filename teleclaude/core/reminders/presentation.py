"""Agent-facing reminder presentation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from teleclaude.core.injected_text import reminder_envelope
from teleclaude.core.session_output import NOOP_SENTINEL

from .models import ReminderEntry, ReminderRecurrence, ReminderTransition, ReminderTrigger

_OPEN = "[Reminder {slug} {occurrence_key} {transition}{schedule}]"
_TIME = " at {occurred_at}"
_NEXT = " next {next_fire_at}"
_EVENT = " on {event_anchor}"
_ARMED = " armed {armed_at}"
_ONE_SHOT = "one-shot"
_RECURRING = "recurring"
_EMPTY = ""
_STALE_INTENT = (
    "Before acting, check for intervening input after the armed time; do not act if it made this intent stale."
)
_SATISFIED_INTENT = (
    "If later input or current state shows this intent is already satisfied, take no reminder-driven tool action "
    "and author no message — no summary, no status, no confirmation. End the turn with exactly "
    f"`{NOOP_SENTINEL}` and no other text."
)
_AUTO_CANCEL_CONSEQUENCE = "Answering with `NOOP` cancels this reminder."


@dataclass(frozen=True)
class ReminderEnvelopeComposition:
    """Rendered firing envelope and its declarative consequences."""

    rendered: str
    body: str
    explicit_noop: bool
    auto_cancel: bool


def _canonical(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def compose_agent_reminder(entry: ReminderEntry) -> ReminderEnvelopeComposition:
    """Render one typed entry in the platform-owned transcript envelope."""
    recurrence = _RECURRING if entry.schedule.recurrence is ReminderRecurrence.RECURRING else _ONE_SHOT
    transition = _EMPTY if entry.transition is ReminderTransition.FIRING else f"{entry.transition.value} "
    if entry.schedule.trigger is ReminderTrigger.AGENT_EVENT:
        event_anchor = entry.schedule.event_anchor
        if event_anchor is None:
            raise ValueError("event reminder entry is missing its anchor")
        schedule = _EVENT.format(event_anchor=event_anchor.value)
    else:
        schedule = _TIME.format(occurred_at=_canonical(entry.occurred_at))
        if entry.schedule.next_fire_at is not None:
            schedule += _NEXT.format(next_fire_at=_canonical(entry.schedule.next_fire_at))
    schedule += _ARMED.format(armed_at=_canonical(entry.armed_at))
    opening = _OPEN.format(
        slug=entry.slug,
        occurrence_key=entry.occurrence_key,
        transition=f"{transition}{recurrence}",
        schedule=schedule,
    )
    body_lines = [entry.intent]
    if entry.transition is ReminderTransition.FIRING:
        body_lines.append(_STALE_INTENT)
        body_lines.append(_SATISFIED_INTENT)
        if entry.auto_cancel:
            body_lines.append(_AUTO_CANCEL_CONSEQUENCE)
    body = "\n".join(body_lines)
    return ReminderEnvelopeComposition(
        rendered=reminder_envelope(opening, body).rendered,
        body=body,
        explicit_noop=entry.transition is ReminderTransition.FIRING,
        auto_cancel=entry.auto_cancel,
    )


def format_agent_reminder(entry: ReminderEntry) -> str:
    """Return the rendered agent-facing reminder envelope."""
    return compose_agent_reminder(entry).rendered


def format_mutation_acknowledgement(entry: ReminderEntry) -> str:
    """Return the concise acknowledgement for one committed transition."""
    return f"{entry.transition.value}: {entry.slug}"
