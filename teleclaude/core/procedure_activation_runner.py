"""Wake, revive or start a procedure's agent for an activation home, and deliver its event.

By default one agent per procedure and home: an activation finds the
system-principal session already holding that pair and delivers to it, or starts
one when none stands. A procedure declaring subject identity has one agent per
subject of its events within the home instead: the session bound to the event's
subject is woken when open, revived with its own transcript when closed, and
started and bound when neither is possible. The home is a company, person or
project registered on this computer, or the platform's own checkout; a company
home sets the session's company and no other home does. The resolve step is
serialized per procedure and home on this computer, covering every subject in
the home; delivery always follows, on start, wake and revival alike, through the
same path later events take.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.caller_identity import SYSTEM_PRINCIPAL_PREFIX
from teleclaude.config.machine import config
from teleclaude.config.referents import ReferentKind, unregistered_referent
from teleclaude.config.registered_homes import registered_home_folder
from teleclaude.config_subjects import ConfigSubjectKind
from teleclaude.constants import ROLE_TASKER, SlashCommand
from teleclaude.core.agent_dispatch import resolve_run_session_thinking_mode
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.db._control_delivery import ProcedureEventRecord
from teleclaude.core.db._sync import SessionIdentityError, resolve_session_principal
from teleclaude.core.inbound.models import InboundSessionPolicy
from teleclaude.core.inbound.resolver import resolve_or_create_bound_session
from teleclaude.core.models import (
    AgentDispatchMode,
    Session,
    SessionEntryPoint,
    SessionLaunchIntent,
    SessionLaunchKind,
)
from teleclaude.core.models._adapter import session_is_unattended
from teleclaude.core.operations._kinds import OPERATION_KIND_PROCEDURE_ACTIVATION
from teleclaude.core.origins import InputOrigin
from teleclaude.core.procedure_event_delivery import (
    ProcedureActivationFailureReason,
    ProcedureActivationTerminalError,
    accept_procedure_activation,
    wake_procedure_events_if_pending,
)
from teleclaude.core.session_revival import revive_session, session_is_resumable
from teleclaude.core.session_startup_message import resolve_command_document
from teleclaude.core.session_status import is_session_terminal
from teleclaude.docs_subscriptions import (
    ProcedureDeliverySettings,
    SubscriptionAttendance,
    SubscriptionHomeKind,
    SubscriptionIdentity,
    required_event_handling_dependencies,
)
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.paths import REPO_ROOT
from teleclaude.types.activation_home import ActivationHome
from teleclaude.types.commands import ActivateProcedureCommand, CreateSessionCommand
from teleclaude.types.procedure_delivery import (
    ActivationOutcome,
    ProcedureActivationResult,
    ProcedureSessionDeliveryInitialization,
)

logger = get_logger(__name__)

#: The root origin-metadata section a subject-bound agent's session records its binding in.
BINDING_SECTION = "procedure_binding"


class BindingField(StrEnum):
    """Persisted key names in a subject-bound agent's ``procedure_binding`` origin section."""

    PROCEDURE = "procedure"
    HOME = "home"
    SUBJECT = "subject"


_PROCEDURE_ACTIVATION_RESOLVED_EVENT = "procedure_activation_resolved"
_PROCEDURE_ACTIVATION_FAILED_EVENT = "procedure_activation_failed"
_PROCEDURE_ACTIVATION_FAILURE_REASON_TEMPLATE = "{reason}: {detail}"
_CANDIDATE_UNRESOLVABLE_EVENT = "procedure_activation_candidate_unresolvable"
_SESSION_ID_FIELD = "session_id"
_NO_SUBJECT_ERROR = "procedure activation names no subject to bind an agent to: {procedure_id} / event {event_id}"
_COMMAND_DOCUMENT_MISSING_ERROR = "generic activation command document is missing: {command}"
_CREATE_RETURNED_NO_SESSION_ERROR = "procedure activation session creation returned no session_id"
_CREATED_SESSION_MISSING_ERROR = "procedure activation session row missing: {session_id}"
_REVIVAL_FAILED_ERROR = "procedure activation could not revive session {session_id} bound to {subject}"
_COMMAND_LINE_TEMPLATE = "/{command} {procedure_id} {home}"
_NO_SESSION_ERROR = "procedure activation could not resolve a session: {procedure_id} / {home}"

_activation_locks: dict[tuple[str, str], asyncio.Lock] = {}
_activation_locks_guard = asyncio.Lock()


@dataclass(frozen=True)
class ProcedureActivationLaunch:
    """The facts that start an activated agent, shared by the runner and a manual run."""

    command_line: str
    job: str
    company: str | None
    system_role: str


def procedure_activation_launch(procedure_id: str, home: ActivationHome) -> ProcedureActivationLaunch:
    """Derive the launch facts for a procedure's standing agent, in one place.

    A hand-started session must be indistinguishable to the runner's ``find``
    from a runner-started one, so both consume this one function. Only a
    company home supplies the session's company.
    """
    return ProcedureActivationLaunch(
        command_line=_COMMAND_LINE_TEMPLATE.format(
            command=SlashCommand.ACTIVATE_PROCEDURE.value, procedure_id=procedure_id, home=home.to_token()
        ),
        job=procedure_id,
        company=home.company,
        system_role=ROLE_TASKER,
    )


def _home_folder(home: ActivationHome) -> Path:
    """The folder a standing agent for the home works in on this computer; raises when the home is absent here."""
    if home.kind is SubscriptionHomeKind.PLATFORM:
        return REPO_ROOT
    folder = registered_home_folder(ConfigSubjectKind(home.kind.value), home.slug)
    if folder is None:
        raise ProcedureActivationTerminalError(
            ProcedureActivationFailureReason.HOME_UNAVAILABLE,
            str(unregistered_referent(ReferentKind(home.kind.value), home.slug)),
        )
    return folder


def _serves_home(session: Session, procedure_id: str, home: ActivationHome, folder: Path) -> bool:
    """Whether the session carries the procedure for the home.

    A company home is identified by the session's company. Any other home is
    identified by the working folder with no company: one procedure answers one
    home kind, so the folder of a home of that kind names it.
    """
    if session.job != procedure_id:
        return False
    if home.company is not None:
        return session.company == home.company
    return (
        session.company is None
        and session.project_path is not None
        and Path(session.project_path).resolve() == folder.resolve()
    )


async def _get_activation_lock(procedure_id: str, home: ActivationHome) -> asyncio.Lock:
    key = (procedure_id, home.to_token())
    async with _activation_locks_guard:
        lock = _activation_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _activation_locks[key] = lock
        return lock


def _system_principal_session(sessions: list[Session]) -> Session | None:
    """The first session, in the order given, running under the system principal.

    Only a survivor of the caller's filters has its principal resolved, and an
    unresolvable one is logged and skipped rather than raised — an open session
    with no identity exists on a live host, and resolving every session's
    principal first would fail every activation while one of them is open.
    """
    for session in sessions:
        try:
            principal, _role = resolve_session_principal(session)
        except SessionIdentityError as exc:
            logger.info(_CANDIDATE_UNRESOLVABLE_EVENT, session_id=session.session_id, error=str(exc))
            continue
        if principal.startswith(SYSTEM_PRINCIPAL_PREFIX):
            return session
    return None


async def _find_standing_session(procedure_id: str, home: ActivationHome, folder: Path) -> tuple[Session | None, int]:
    """Return the most recently active qualifying session, and how many candidates matched."""
    candidates = await db.list_sessions(computer_name=config.computer.name, all_open=True)
    matching = [session for session in candidates if _serves_home(session, procedure_id, home, folder)]
    matching.sort(key=lambda session: session.last_activity or session.created_at or "", reverse=True)
    return _system_principal_session(matching), len(matching)


def _subject_token(cmd: ActivateProcedureCommand) -> str:
    """The token of the subject the activating event is about; raises when the event names none."""
    event = ReceivedEvent.model_validate_json(cmd.event_json)
    if event.subject is None:
        raise ProcedureActivationTerminalError(
            ProcedureActivationFailureReason.SUBJECT_MISSING,
            _NO_SUBJECT_ERROR.format(procedure_id=cmd.procedure_id, event_id=event.id),
        )
    return event.subject.to_token()


def _is_open(session: Session) -> bool:
    return not is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at)


async def _find_bound_sessions(
    procedure_id: str, home: ActivationHome, folder: Path, subject: str
) -> tuple[Session | None, Session | None]:
    """The open and the resumable closed system-principal sessions bound to the subject, newest first.

    The binding section names the subject; the session's job and home say which
    procedure and home it was started for. Closed sessions are included, since a
    later event about the subject revives them — except an unattended agent's,
    which is a run that is done, judged by the session's own stamp.
    """
    bound = await db.get_sessions_by_origin_metadata(
        BINDING_SECTION, BindingField.SUBJECT, subject, include_closed=True
    )
    serving = [
        session
        for session in bound
        if session.computer_name == config.computer.name and _serves_home(session, procedure_id, home, folder)
    ]
    open_session = _system_principal_session([session for session in serving if _is_open(session)])
    closed_session = _system_principal_session(
        [
            session
            for session in serving
            if not _is_open(session) and session_is_resumable(session) and not session_is_unattended(session)
        ]
    )
    return open_session, closed_session


async def _create_agent(
    cmd: ActivateProcedureCommand,
    activation: ProcedureEventRecord,
    home: ActivationHome,
    folder: Path,
    attendance: SubscriptionAttendance,
    subject: str | None = None,
) -> Session:
    """Start the procedure's agent in the home's folder and return its session.

    An unattended procedure's agent is stamped unattended in the creating write.
    """
    procedure_id = cmd.procedure_id
    launch = procedure_activation_launch(procedure_id, home)
    if resolve_command_document(SlashCommand.ACTIVATE_PROCEDURE.value) is None:
        raise ProcedureActivationTerminalError(
            ProcedureActivationFailureReason.COMMAND_UNAVAILABLE,
            _COMMAND_DOCUMENT_MISSING_ERROR.format(command=SlashCommand.ACTIVATE_PROCEDURE.value),
        )
    thinking_mode = resolve_run_session_thinking_mode(caller_mode=None, command=SlashCommand.ACTIVATE_PROCEDURE)
    pending_events = await db.list_procedure_events(
        responsibility_key=activation.responsibility_key,
        include_suspended=True,
    )
    activation_ids = tuple(event.activation_id for event in pending_events)
    if activation.activation_id not in activation_ids:
        activation_ids = (*activation_ids, activation.activation_id)
    create_cmd = CreateSessionCommand(
        project_path=str(folder),
        origin=InputOrigin.TERMINAL.value,
        initial_input=launch.command_line,
        command=SlashCommand.ACTIVATE_PROCEDURE.value,
        system_role=launch.system_role,
        job=launch.job,
        company=launch.company,
        launch_intent=SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
            message=launch.command_line,
            thinking_mode=thinking_mode.value,
            dispatch_mode=AgentDispatchMode.AUTOMATIC,
        ),
        entry_point=SessionEntryPoint.PROCEDURE_ACTIVATION,
        unattended=attendance is SubscriptionAttendance.UNATTENDED,
        origin_metadata=(
            {
                BINDING_SECTION: {
                    BindingField.PROCEDURE.value: procedure_id,
                    BindingField.HOME.value: home.to_token(),
                    BindingField.SUBJECT.value: subject,
                }
            }
            if subject is not None
            else None
        ),
        procedure_delivery=ProcedureSessionDeliveryInitialization(
            procedure_id=procedure_id,
            responsibility_key=activation.responsibility_key,
            activation_ids=activation_ids,
            event_delivery=cmd.event_delivery,
            interruptible=cmd.interruptible,
            initial_entry_id=activation.activation_id,
            required_reads=required_event_handling_dependencies(
                ProcedureDeliverySettings(
                    event_delivery=cmd.event_delivery,
                    interruptible=cmd.interruptible,
                )
            ),
        ),
    )
    result = await get_command_service().create_session(create_cmd)
    session_id_raw = result.get(_SESSION_ID_FIELD)
    if not session_id_raw:
        raise ProcedureActivationTerminalError(
            ProcedureActivationFailureReason.SESSION_UNAVAILABLE,
            _CREATE_RETURNED_NO_SESSION_ERROR,
        )
    session = await db.get_session(str(session_id_raw))
    if session is None:
        raise ProcedureActivationTerminalError(
            ProcedureActivationFailureReason.SESSION_UNAVAILABLE,
            _CREATED_SESSION_MISSING_ERROR.format(session_id=session_id_raw),
        )
    return session


@dataclass(frozen=True)
class _Resolution:
    """The agent an activation resolved to, how it was reached, and how many candidates were considered."""

    session: Session
    outcome: ActivationOutcome
    candidate_count: int


async def _resolve_home_agent(
    cmd: ActivateProcedureCommand,
    activation: ProcedureEventRecord,
    home: ActivationHome,
    folder: Path,
    attendance: SubscriptionAttendance,
) -> _Resolution:
    """The home's one agent: the standing session when one stands, otherwise a started one."""
    procedure_id = cmd.procedure_id
    candidate_count = 0

    async def _find() -> Session | None:
        nonlocal candidate_count
        session, candidate_count = await _find_standing_session(procedure_id, home, folder)
        return session

    async def _create() -> Session | None:
        return await _create_agent(cmd, activation, home, folder, attendance)

    async def _reconcile(session: Session) -> Session:
        return session

    policy = InboundSessionPolicy(find=_find, create=_create, reconcile=_reconcile)
    session, is_new = await resolve_or_create_bound_session(policy)
    if session is None:
        raise ProcedureActivationTerminalError(
            ProcedureActivationFailureReason.SESSION_UNAVAILABLE,
            _NO_SESSION_ERROR.format(procedure_id=procedure_id, home=home.to_token()),
        )
    return _Resolution(session, ActivationOutcome.STARTED if is_new else ActivationOutcome.WOKEN, candidate_count)


async def _resolve_subject_agent(
    cmd: ActivateProcedureCommand, activation: ProcedureEventRecord, home: ActivationHome, folder: Path
) -> _Resolution:
    """The agent bound to the event's subject: woken when open, revived when closed and attended, otherwise started and bound."""
    procedure_id = cmd.procedure_id
    subject = _subject_token(cmd)
    open_session, closed_session = await _find_bound_sessions(procedure_id, home, folder, subject)
    candidate_count = sum(session is not None for session in (open_session, closed_session))
    if open_session is not None:
        return _Resolution(open_session, ActivationOutcome.WOKEN, candidate_count)
    if closed_session is not None:
        if not await revive_session(closed_session.session_id):
            raise ProcedureActivationTerminalError(
                ProcedureActivationFailureReason.REVIVAL_FAILED,
                _REVIVAL_FAILED_ERROR.format(session_id=closed_session.session_id, subject=subject),
            )
        revived = await db.get_session(closed_session.session_id)
        if revived is None:
            raise ProcedureActivationTerminalError(
                ProcedureActivationFailureReason.SESSION_UNAVAILABLE,
                _CREATED_SESSION_MISSING_ERROR.format(session_id=closed_session.session_id),
            )
        return _Resolution(revived, ActivationOutcome.REVIVED, candidate_count)
    created = await _create_agent(cmd, activation, home, folder, cmd.attendance, subject=subject)
    return _Resolution(created, ActivationOutcome.STARTED, candidate_count)


async def activate(cmd: ActivateProcedureCommand) -> ProcedureActivationResult:
    """Wake, revive or start the procedure's agent for the home, then deliver the event.

    The agent is the home's one agent, or — for a procedure declaring subject
    identity — the agent bound to the event's subject. Raises on any failure —
    the home is absent on this computer, no command document, create returned no
    session, a subject-identity event names no subject, a revival fails, or
    delivery raised — so the operation fails with its reason.
    """
    procedure_id = cmd.procedure_id
    home = ActivationHome.from_token(cmd.home)
    lock = await _get_activation_lock(procedure_id, home)
    async with lock:
        activation = await accept_procedure_activation(cmd)
        try:
            folder = _home_folder(home)
            if cmd.identity is SubscriptionIdentity.SUBJECT:
                resolution = await _resolve_subject_agent(cmd, activation, home, folder)
            else:
                resolution = await _resolve_home_agent(cmd, activation, home, folder, cmd.attendance)
        except ProcedureActivationTerminalError as exc:
            reason = _PROCEDURE_ACTIVATION_FAILURE_REASON_TEMPLATE.format(
                reason=exc.reason.value,
                detail=exc.detail,
            )
            if exc.reason is ProcedureActivationFailureReason.SUBJECT_MISSING:
                failed_count = await db.fail_procedure_event(activation_id=activation.activation_id, reason=reason)
            else:
                failed_count = await db.fail_procedure_responsibility_events(
                    responsibility_key=activation.responsibility_key,
                    reason=reason,
                )
            logger.error(
                _PROCEDURE_ACTIVATION_FAILED_EVENT,
                activation_id=activation.activation_id,
                procedure_id=procedure_id,
                home=home.to_token(),
                failed_count=failed_count,
                reason=exc.reason.value,
            )
            raise
        if resolution.outcome is not ActivationOutcome.STARTED:
            await db.reassign_procedure_events(
                responsibility_key=activation.responsibility_key,
                session_id=resolution.session.session_id,
            )
            await wake_procedure_events_if_pending(session_id=resolution.session.session_id)

        operation_row = await db.get_operation_by_request(
            kind=OPERATION_KIND_PROCEDURE_ACTIVATION, caller_session_id=None, client_request_id=cmd.request_id or ""
        )
        logger.info(
            _PROCEDURE_ACTIVATION_RESOLVED_EVENT,
            procedure_id=procedure_id,
            home=home.to_token(),
            identity=cmd.identity.value,
            operation_id=operation_row.operation_id if operation_row is not None else "",
            activation_id=cmd.request_id or "",
            session_id=resolution.session.session_id,
            outcome=resolution.outcome.value,
            candidate_count=resolution.candidate_count,
        )
        return {"session_id": resolution.session.session_id, "outcome": resolution.outcome}
