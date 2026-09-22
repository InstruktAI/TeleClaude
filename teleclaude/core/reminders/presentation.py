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
    "Before acting, check for intervening input after the armed time. If it made this intent stale, do not carry "
    "the intent out; reconcile the reminder using the rule below."
)
_SATISFIED_ONE_SHOT_INTENT = (
    "If later input or current state shows this intent is already satisfied or obsolete, author no message — no "
    "summary, no status, no confirmation — and end the turn with exactly "
    f"`{NOOP_SENTINEL}` and no other text. This one-shot firing has already consumed the reminder."
)
_SATISFIED_MANUAL_CANCEL_INTENT = (
    "If later input or current state shows this intent is already satisfied or obsolete, cancel this reminder with "
    "`telec reminders cancel {slug}`, then author no message — no summary, no status, no confirmation — and end "
    f"the turn with exactly `{NOOP_SENTINEL}` and no other text."
)
_FIRING_HISTORY = "Occurrence {firing_number}; armed {elapsed} ago."
_HOUR_SECONDS = 3600
_MINUTE_SECONDS = 60
_HOUR_PART = "{value}h"
_MINUTE_PART = "{value}m"
_SECOND_PART = "{value}s"


@dataclass(frozen=True)
class ReminderEnvelopeComposition:
    """Rendered firing envelope and its declarative consequences."""

    rendered: str
    body: str
    explicit_noop: bool


def _canonical(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _format_elapsed_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, _HOUR_SECONDS)
    minutes, remaining_seconds = divmod(remainder, _MINUTE_SECONDS)
    parts: list[str] = []
    if hours:
        parts.append(_HOUR_PART.format(value=hours))
    if minutes:
        parts.append(_MINUTE_PART.format(value=minutes))
    if remaining_seconds or not parts:
        parts.append(_SECOND_PART.format(value=remaining_seconds))
    return " ".join(parts)


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
        body_lines.append(
            _FIRING_HISTORY.format(
                firing_number=entry.firing_number,
                elapsed=_format_elapsed_duration(entry.elapsed_since_armed_seconds),
            )
        )
        body_lines.append(_STALE_INTENT)
        if entry.schedule.recurrence is ReminderRecurrence.ONE_SHOT:
            body_lines.append(_SATISFIED_ONE_SHOT_INTENT)
        else:
            body_lines.append(_SATISFIED_MANUAL_CANCEL_INTENT.format(slug=entry.slug))
    body = "\n".join(body_lines)
    return ReminderEnvelopeComposition(
        rendered=reminder_envelope(opening, body).rendered,
        body=body,
        explicit_noop=entry.transition is ReminderTransition.FIRING,
    )


def format_agent_reminder(entry: ReminderEntry) -> str:
    """Return the rendered agent-facing reminder envelope."""
    return compose_agent_reminder(entry).rendered


def format_mutation_acknowledgement(entry: ReminderEntry) -> str:
    """Return the concise acknowledgement for one committed transition."""
    return f"{entry.transition.value}: {entry.slug}"
