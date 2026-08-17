"""Agent- and human-facing reminder presentation."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from teleclaude.core.session_output import NOOP_SENTINEL

from .models import ReminderEntry, ReminderRecurrence, ReminderTransition, ReminderTrigger

_OPEN = "[Reminder {slug} {transition}{schedule}]"
_CLOSE = "[/Reminder {slug}]"
_TIME = " at {occurred_at}"
_NEXT = " next {next_fire_at}"
_EVENT = " on {event_anchor}"
_ARMED = " armed {armed_at}"
_ONE_SHOT = "one-shot"
_RECURRING = "recurring"
_EMPTY = ""
_LOCAL_TIME_FORMAT = "%d %b %Y, %H:%M %Z"
_STALE_INTENT = (
    "Before acting, check for intervening input after the armed time; do not act if it made this intent stale."
)
_SATISFIED_INTENT = (
    "If later input or current state shows this intent is already satisfied, take no reminder-driven tool action "
    "and author no message — no summary, no status, no confirmation. End the turn silently when possible; "
    f"if the runtime requires turn-complete text, emit exactly `{NOOP_SENTINEL}` and no other text."
)


def _canonical(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def format_agent_reminder(entry: ReminderEntry) -> str:
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
    opening = _OPEN.format(slug=entry.slug, transition=f"{transition}{recurrence}", schedule=schedule)
    closing = _CLOSE.format(slug=entry.slug)
    lines = [opening, entry.intent]
    if entry.transition is ReminderTransition.FIRING:
        lines.append(_STALE_INTENT)
        lines.append(_SATISFIED_INTENT)
    lines.append(closing)
    return "\n".join(lines)


def format_ui_reminder(entry: ReminderEntry, *, timezone_name: str) -> str:
    """Render one typed source entry as envelope-free UI Markdown."""
    fields = [
        f"**Reminder:** `{entry.slug}`",
        f"**Type:** {entry.schedule.recurrence.value.replace('_', ' ').title()}",
    ]
    if entry.schedule.trigger is ReminderTrigger.AGENT_EVENT:
        if entry.schedule.event_anchor is None:
            raise ValueError("event reminder entry is missing its anchor")
        fields.append(f"**Triggered:** `{entry.schedule.event_anchor.value}`")
    else:
        fields.append(f"**Triggered:** `{_format_local(entry.occurred_at, timezone_name=timezone_name)}`")
    if entry.schedule.next_fire_at is not None and (
        entry.transition is not ReminderTransition.FIRING or entry.schedule.recurrence is ReminderRecurrence.RECURRING
    ):
        fields.append(f"**Next:** `{_format_local(entry.schedule.next_fire_at, timezone_name=timezone_name)}`")
    fields.append(f"**Intent:** {entry.intent}")
    if entry.transition is not ReminderTransition.FIRING:
        fields.append(f"**Status:** {entry.transition.value.title()}")
    return "\n".join(fields)


def _format_local(value: datetime, *, timezone_name: str) -> str:
    local = value.astimezone(ZoneInfo(timezone_name))
    return f"{local.strftime(_LOCAL_TIME_FORMAT)} ({timezone_name})"
