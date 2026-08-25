"""Authenticated self-session reminder API."""

from __future__ import annotations

import re
from datetime import datetime
from math import isfinite
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, require_clearance
from teleclaude.api_models import (
    ReminderDTO,
    ReminderEntryDTO,
    ReminderMutationResponseDTO,
    SetReminderRequest,
)
from teleclaude.core.reminders import (
    PrescribedReminderInput,
    PrescribedReminderSlug,
    Reminder,
    ReminderEntry,
    ReminderSchedule,
    ReminderSetRequest,
    accepted_prescribed_parameters,
)
from teleclaude.core.reminders.presentation import format_mutation_acknowledgement

if TYPE_CHECKING:
    from teleclaude.core.reminders import ReminderService

logger = get_logger(__name__)

router = APIRouter(prefix="/reminders", tags=["reminders"])

_reminder_service: ReminderService | None = None
_DURATION_PART = re.compile(r"(?P<value>\d+(?:\.\d+)?)(?P<unit>[smhd])")
_DURATION_MULTIPLIERS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
_API_OUTCOME_EVENT = "reminder_api_outcome"
_SERVICE_UNAVAILABLE = "reminder service is not configured"
_SESSION_REQUIRED = "reminder commands require an authenticated caller session"
_GENERIC_SHAPE_ERROR = "generic reminders require exactly one of after or at and an intent"
_REPEAT_SHAPE_ERROR = "repeat requires a relative after schedule"
_PRESCRIBED_FIELD_ERROR = "prescribed reminder received unsupported parameters"
_RFC3339_ERROR = "at must be an RFC3339 timestamp with an explicit timezone"
_DURATION_ERROR = "duration must be a finite positive interval"

_set_clearance = require_clearance("telec reminders set")
_list_clearance = require_clearance("telec reminders list")
_cancel_clearance = require_clearance("telec reminders cancel")


def configure(service: ReminderService | None) -> None:
    """Wire the daemon-owned reminder service."""
    global _reminder_service
    _reminder_service = service


def _service() -> ReminderService:
    service = _reminder_service
    if service is None:
        raise HTTPException(status_code=503, detail=_SERVICE_UNAVAILABLE)
    return service


def _session_id(identity: CallerIdentity) -> str:
    if not identity.session_id:
        raise HTTPException(status_code=403, detail=_SESSION_REQUIRED)
    return identity.session_id


def _parse_duration(value: str) -> float:
    position = 0
    total = 0.0
    for match in _DURATION_PART.finditer(value):
        if match.start() != position:
            raise ValueError(_DURATION_ERROR)
        total += float(match.group("value")) * _DURATION_MULTIPLIERS[match.group("unit")]
        position = match.end()
    if position != len(value) or position == 0:
        raise ValueError(_DURATION_ERROR)
    if not isfinite(total) or total <= 0:
        raise ValueError(_DURATION_ERROR)
    return total


def _parse_rfc3339(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(_RFC3339_ERROR) from exc
    if parsed.tzinfo is None:
        raise ValueError(_RFC3339_ERROR)
    return parsed


def _generic_request(session_id: str, request: SetReminderRequest) -> ReminderSetRequest:
    if request.intent is None or (request.after is None) == (request.at is None):
        raise ValueError(_GENERIC_SHAPE_ERROR)
    if request.repeat and request.after is None:
        raise ValueError(_REPEAT_SHAPE_ERROR)
    schedule = (
        ReminderSchedule.relative(after_seconds=_parse_duration(request.after), repeat=request.repeat)
        if request.after is not None
        else ReminderSchedule.absolute(at=_parse_rfc3339(request.at))
    )
    return ReminderSetRequest(
        session_id=session_id,
        slug=request.slug,
        intent=request.intent,
        schedule=schedule,
    )


def _prescribed_inputs(slug: PrescribedReminderSlug, request: SetReminderRequest) -> PrescribedReminderInput:
    after_seconds = _parse_duration(request.after) if request.after is not None else None
    supplied = {
        "intent": request.intent,
        "at": request.at,
        "repeat": request.repeat or None,
        "target_slug": request.target_slug,
        "after": request.after,
    }
    accepted = accepted_prescribed_parameters(slug)
    unsupported = {name for name, value in supplied.items() if value is not None and name not in accepted}
    if unsupported:
        raise ValueError(_PRESCRIBED_FIELD_ERROR)
    return PrescribedReminderInput(
        intent=request.intent,
        target_slug=request.target_slug,
        after_seconds=after_seconds,
    )


def _reminder_dto(reminder: Reminder) -> ReminderDTO:
    schedule = reminder.schedule
    return ReminderDTO(
        slug=reminder.slug,
        profile=reminder.profile.value if reminder.profile is not None else None,
        intent=reminder.intent,
        trigger=schedule.trigger.value,
        recurrence=schedule.recurrence.value,
        event_anchor=schedule.event_anchor.value if schedule.event_anchor is not None else None,
        interval_seconds=schedule.interval_seconds,
        armed_at=reminder.armed_at.isoformat(),
        next_fire_at=schedule.next_fire_at.isoformat() if schedule.next_fire_at is not None else None,
        generation=reminder.generation,
    )


def _entry_dto(entry: ReminderEntry) -> ReminderEntryDTO:
    schedule = entry.schedule
    return ReminderEntryDTO(
        entry_id=entry.entry_id,
        slug=entry.slug,
        transition=entry.transition.value,
        profile=entry.profile,
        intent=entry.intent,
        trigger=schedule.trigger.value,
        recurrence=schedule.recurrence.value,
        event_anchor=schedule.event_anchor.value if schedule.event_anchor is not None else None,
        interval_seconds=schedule.interval_seconds,
        armed_at=entry.armed_at.isoformat(),
        occurred_at=entry.occurred_at.isoformat(),
        next_fire_at=schedule.next_fire_at.isoformat() if schedule.next_fire_at is not None else None,
        generation=entry.generation,
    )


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "reminder_request_id", None)
    return str(value) if value is not None else None


def _observe_outcome(
    request: Request,
    *,
    outcome: str,
    identity: CallerIdentity,
    slug: str | None,
    reason: str | None = None,
    presentation_mode: str | None = None,
) -> None:
    logger.info(
        _API_OUTCOME_EVENT,
        request_id=_request_id(request),
        owner_session_id=identity.session_id,
        slug=slug,
        outcome=outcome,
        reason=reason,
        presentation_mode=presentation_mode,
    )


@router.post("")
async def set_reminder(
    request: Request,
    body: SetReminderRequest,
    identity: CallerIdentity = Depends(_set_clearance),
) -> ReminderMutationResponseDTO:
    """Arm or replace a reminder owned by the authenticated session."""
    session_id = _session_id(identity)
    try:
        prescribed = PrescribedReminderSlug(body.slug)
    except ValueError:
        prescribed = None
    try:
        if prescribed is None:
            entry = await _service().set(_generic_request(session_id, body))
        else:
            entry = await _service().set_prescribed(
                session_id=session_id,
                slug=prescribed,
                inputs=_prescribed_inputs(prescribed, body),
            )
    except (ValueError, TypeError) as exc:
        reason = "prescribed_profile_required" if prescribed is not None and body.intent is not None else "validation"
        _observe_outcome(request, outcome="rejected", identity=identity, slug=body.slug, reason=reason)
        detail = (
            f"{body.slug} is a prescribed profile; invoke it with its registered profile parameters"
            if reason == "prescribed_profile_required"
            else str(exc)
        )
        raise HTTPException(status_code=422, detail=detail) from exc
    presentation = format_mutation_acknowledgement(entry)
    _observe_outcome(
        request,
        outcome="success",
        identity=identity,
        slug=body.slug,
        presentation_mode="minimal_ack",
    )
    return ReminderMutationResponseDTO(
        outcome="success",
        entry=_entry_dto(entry),
        presentation=presentation,
    )


@router.get("")
async def list_reminders(identity: CallerIdentity = Depends(_list_clearance)) -> list[ReminderDTO]:
    """List every live reminder owned by the authenticated session."""
    reminders = await _service().list(session_id=_session_id(identity))
    return [_reminder_dto(reminder) for reminder in reminders]


@router.delete("")
async def cancel_all_reminders(
    request: Request,
    all_reminders: bool = Query(alias="all"),
    identity: CallerIdentity = Depends(_cancel_clearance),
) -> list[ReminderMutationResponseDTO]:
    """Idempotently cancel every caller-owned reminder."""
    if not all_reminders:
        raise HTTPException(status_code=422, detail="all=true is required")
    entries = await _service().cancel_all(session_id=_session_id(identity))
    _observe_outcome(
        request,
        outcome="success",
        identity=identity,
        slug=None,
        presentation_mode="minimal_ack",
    )
    return [
        ReminderMutationResponseDTO(
            outcome="success",
            entry=_entry_dto(entry),
            presentation=format_mutation_acknowledgement(entry),
        )
        for entry in entries
    ]


@router.delete("/{slug}")
async def cancel_reminder(
    slug: str,
    request: Request,
    identity: CallerIdentity = Depends(_cancel_clearance),
) -> ReminderMutationResponseDTO:
    """Idempotently cancel one caller-owned reminder."""
    entry = await _service().cancel(session_id=_session_id(identity), slug=slug)
    outcome = "success" if entry is not None else "already_absent"
    presentation = format_mutation_acknowledgement(entry) if entry is not None else None
    _observe_outcome(
        request,
        outcome=outcome,
        identity=identity,
        slug=slug,
        presentation_mode="minimal_ack" if presentation is not None else None,
    )
    return ReminderMutationResponseDTO(
        outcome=outcome,
        entry=_entry_dto(entry) if entry is not None else None,
        presentation=presentation,
    )
