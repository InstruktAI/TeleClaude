"""Runtime-owned persistence and identity for subscribed procedure events."""

from __future__ import annotations

import json
from enum import StrEnum

from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.db._control_delivery import ProcedureEventRecord
from teleclaude.core.injected_text import (
    InjectedTextSourceFeature,
    TranscriptEntryKind,
    render_bracket_envelope,
    wake_envelope,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_status import is_agent_turn_running
from teleclaude.docs_subscriptions import SubscriptionIdentity
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.types.commands import ActivateProcedureCommand, ProcessMessageCommand

_ACTIVATION_ID_REQUIRED_ERROR = "procedure activation has no identity"
_SUBJECT_REQUIRED_ERROR = "subject-bound procedure activation has no event subject"
_COMPACT_JSON_SEPARATORS = (",", ":")
_ENSURE_ASCII = True
_PROCEDURE_WAKE_ACTOR = "system"


class ProcedureActivationFailureReason(StrEnum):
    HOME_UNAVAILABLE = "home_unavailable"
    PROCEDURE_UNAVAILABLE = "procedure_unavailable"
    SESSION_UNAVAILABLE = "session_unavailable"
    SUBJECT_MISSING = "subject_missing"
    REVIVAL_FAILED = "revival_failed"


class ProcedureActivationTerminalError(RuntimeError):
    """A durable procedure activation cannot continue under its current identity."""

    def __init__(self, reason: ProcedureActivationFailureReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(detail)


def procedure_responsibility_key(*, procedure_id: str, home: str, subject: str | None) -> str:
    """Return a stable key for a procedure agent independently of its session."""
    return json.dumps((procedure_id, home, subject), ensure_ascii=_ENSURE_ASCII, separators=_COMPACT_JSON_SEPARATORS)


def procedure_responsibility_parts(responsibility_key: str) -> tuple[str, str, str | None]:
    """Read a responsibility key back into its procedure ID, home token and optional subject token."""
    procedure_id, home, subject = json.loads(responsibility_key)
    return str(procedure_id), str(home), (str(subject) if subject is not None else None)


async def accept_procedure_activation(command: ActivateProcedureCommand) -> ProcedureEventRecord:
    """Persist one activation under its home or subject responsibility identity."""
    activation_id = command.request_id
    if not activation_id:
        raise ValueError(_ACTIVATION_ID_REQUIRED_ERROR)
    event = ReceivedEvent.model_validate_json(command.event_json)
    subject: str | None = None
    if command.identity is SubscriptionIdentity.SUBJECT:
        if event.subject is None:
            raise ValueError(_SUBJECT_REQUIRED_ERROR)
        subject = event.subject.to_token()
    responsibility_key = procedure_responsibility_key(
        procedure_id=command.procedure_id,
        home=command.home,
        subject=subject,
    )
    return await db.accept_procedure_event(
        activation_id=activation_id,
        responsibility_key=responsibility_key,
        procedure_id=command.procedure_id,
        home=command.home,
        subject=subject,
        event_json=command.event_json,
        identity=command.identity,
        attendance=command.attendance,
        event_delivery=command.event_delivery,
        interruptible=command.interruptible,
    )


async def wake_procedure_events_if_pending(*, session_id: str) -> None:
    """Offer pending responsibility work through the shared correlated idle wake."""
    session = await db.get_session(session_id)
    if session is None or is_agent_turn_running(
        last_input_at=session.last_message_sent_at,
        last_agent_stop_at=session.last_agent_stop_at,
        last_agent_idle_at=session.last_agent_idle_at,
    ):
        return
    if not session.receives_terminal_input:
        # A wake is typed input, which would adopt a hook-only session; its pending events wait for its next hook boundary.
        return
    occurrence_id = await db.prepare_procedure_event_wake_opportunity(session_id=session_id)
    if occurrence_id is None:
        return
    await get_command_service().process_message(
        ProcessMessageCommand(
            session_id=session_id,
            text=render_bracket_envelope(wake_envelope(occurrence_id)),
            origin=InputOrigin.TERMINAL.value,
            text_kind=TranscriptEntryKind.PLATFORM_CONTROL,
            source_feature=InjectedTextSourceFeature.PROCEDURE_ACTIVATION,
            occurrence_key=occurrence_id,
            source_message_id=occurrence_id,
            actor_name=_PROCEDURE_WAKE_ACTOR,
        )
    )
