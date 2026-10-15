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
import uuid
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.caller_identity import SYSTEM_PRINCIPAL_PREFIX
from teleclaude.config.machine import config
from teleclaude.config.referents import ReferentKind, unregistered_referent
from teleclaude.config.registered_homes import registered_home_folder
from teleclaude.config_subjects import ConfigSubjectKind
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.db._control_delivery import ProcedureEventRecord
from teleclaude.core.db._sync import SessionIdentityError, resolve_session_principal
from teleclaude.core.db_models import ProcedureEventDeliveryOutcome
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
from teleclaude.core.operations._kinds import OperationKind
from teleclaude.core.origins import InputOrigin
from teleclaude.core.procedure_entry import EntryRefusal, activation_entry, resolve_entry
from teleclaude.core.procedure_event_delivery import (
    ProcedureActivationFailureReason,
    ProcedureActivationTerminalError,
    accept_procedure_activation,
    wake_procedure_events_if_pending,
)
from teleclaude.core.session_revival import revive_session, session_is_resumable
from teleclaude.core.session_status import is_session_terminal
from teleclaude.core.workflow_machine.publication import DriverInitialization, driver_initialization
from teleclaude.core.workflow_machine.single_claim import (
    EventFacts,
    ItemFacts,
    declares_single_claim,
    entitled_to_request,
    event_facts,
    judge,
    read_item_facts,
    session_is_single_claim,
)
from teleclaude.docs_subscriptions import (
    ProcedureDeliverySettings,
    SubscriptionAttendance,
    SubscriptionHomeKind,
    SubscriptionIdentity,
)
from teleclaude.entry_declarations import SessionMode
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.paths import REPO_ROOT
from teleclaude.types.activation_home import ActivationHome
from teleclaude.types.commands import ActivateProcedureCommand, CreateSessionCommand
from teleclaude.types.procedure_delivery import (
    BINDING_SECTION,
    ActivationOutcome,
    BindingField,
    NotDeliveredReason,
    ProcedureActivationResult,
    ProcedureSessionDeliveryInitialization,
)

logger = get_logger(__name__)

_PROCEDURE_ACTIVATION_RESOLVED_EVENT = "procedure_activation_resolved"
_PROCEDURE_ACTIVATION_FAILED_EVENT = "procedure_activation_failed"
_PROCEDURE_ACTIVATION_NOT_DELIVERED_EVENT = "procedure_activation_not_delivered"
_PROCEDURE_ACTIVATION_FAILURE_REASON_TEMPLATE = "{reason}: {detail}"
_CANDIDATE_UNRESOLVABLE_EVENT = "procedure_activation_candidate_unresolvable"
_SESSION_ID_FIELD = "session_id"
_NO_SUBJECT_ERROR = "procedure activation names no subject to bind an agent to: {procedure_id} / event {event_id}"
_CREATE_RETURNED_NO_SESSION_ERROR = "procedure activation session creation returned no session_id"
_CREATED_SESSION_MISSING_ERROR = "procedure activation session row missing: {session_id}"
_REVIVAL_FAILED_ERROR = "procedure activation could not revive session {session_id} bound to {subject}"
_INITIAL_INPUT_TEMPLATE = "{procedure_id} {home}"
_NO_SESSION_ERROR = "procedure activation could not resolve a session: {procedure_id} / {home}"

_activation_locks: dict[tuple[str, str], asyncio.Lock] = {}
_activation_locks_guard = asyncio.Lock()


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
    own_row_only: bool = False,
    initialization: DriverInitialization | None = None,
    single_claim: bool = False,
) -> Session:
    """Start the procedure's agent in the home's folder and return its session.

    An unattended procedure's agent is stamped unattended in the creating write.
    """
    procedure_id = cmd.procedure_id
    session_id = str(uuid.uuid4())
    initialization = initialization or driver_initialization(procedure_id)
    try:
        resolved = resolve_entry(
            procedure_token=procedure_id,
            arguments="",
            project_root=folder,
            caller=None,
            entry=activation_entry(
                procedure_id=procedure_id,
                home=home.to_token(),
                subject=subject,
                attendance=attendance,
                delivery=ProcedureDeliverySettings(event_delivery=cmd.event_delivery, interruptible=cmd.interruptible),
                workflow_publication=initialization.snapshot,
            ),
            pinned=initialization.declarations,
            caller_mode=None,
        )
    except EntryRefusal as exc:
        raise ProcedureActivationTerminalError(
            ProcedureActivationFailureReason.PROCEDURE_UNAVAILABLE, exc.detail
        ) from exc
    pending_events = (
        []
        if own_row_only
        else await db.list_procedure_events(responsibility_key=activation.responsibility_key, include_suspended=True)
    )
    activation_ids = tuple(event.activation_id for event in pending_events)
    if activation.activation_id not in activation_ids:
        activation_ids = (*activation_ids, activation.activation_id)
    create_cmd = CreateSessionCommand(
        session_id=session_id,
        project_path=str(folder),
        origin=InputOrigin.TERMINAL.value,
        initial_input=_INITIAL_INPUT_TEMPLATE.format(procedure_id=procedure_id, home=home.to_token()),
        command=resolved.procedure_id,
        role=resolved.role.name.value,
        job=resolved.entry.job,
        company=home.company,
        launch_intent=SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
            message=resolved.loader,
            thinking_mode=resolved.thinking_mode.value,
            dispatch_mode=AgentDispatchMode.AUTOMATIC,
            candidate_order=resolved.agents,
            invocation=resolved.record,
        ),
        entry_point=SessionEntryPoint.PROCEDURE_ACTIVATION,
        unattended=attendance is SubscriptionAttendance.UNATTENDED,
        origin_metadata=(
            {
                BINDING_SECTION: {
                    BindingField.PROCEDURE.value: procedure_id,
                    BindingField.HOME.value: home.to_token(),
                    BindingField.SUBJECT.value: subject,
                    **({BindingField.SESSION_MODE.value: SessionMode.SINGLE_CLAIM.value} if single_claim else {}),
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
class _NotDelivered:
    """An activation of a single-claim responsibility that delivers nothing, by decision."""

    reason: NotDeliveredReason


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


async def _item_for_home(folder: Path, facts: EventFacts) -> ItemFacts | None:
    """The item the event names, only when the event's project is the home's own."""
    if facts.project_path and Path(facts.project_path).resolve() != folder.resolve():
        return None
    return await read_item_facts(folder, facts.slug)


async def _is_single_claim_activation(
    cmd: ActivateProcedureCommand, home: ActivationHome, folder: Path, initialization: DriverInitialization
) -> bool:
    """Whether this activation is handled as a single-claim responsibility, by one captured initialization.

    A session already bound to the item keeps the mode it was initialized with, recorded on its binding and never
    reread from the current publication; with none, the one initialization captured for this activation decides.
    """
    open_session, _closed = await _find_bound_sessions(cmd.procedure_id, home, folder, _subject_token(cmd))
    if open_session is not None:
        return session_is_single_claim(open_session)
    return declares_single_claim(initialization.declarations)


async def _resolve_single_claim(
    cmd: ActivateProcedureCommand,
    activation: ProcedureEventRecord,
    home: ActivationHome,
    folder: Path,
    initialization: DriverInitialization,
) -> _Resolution | _NotDelivered:
    """A request starts or wakes a driver for the current reservation; a notice reaches only the holder.

    A closed session is never revived. A fresh session takes only the row of this activation.
    """
    subject = _subject_token(cmd)
    facts = event_facts(cmd.event_json)
    item = await _item_for_home(folder, facts)
    open_session, _closed = await _find_bound_sessions(cmd.procedure_id, home, folder, subject)
    reason = judge(facts, item, open_session.session_id if open_session is not None else "")
    if reason is not None:
        return _NotDelivered(reason)
    if not facts.is_request:
        if open_session is None:
            return _NotDelivered(NotDeliveredReason.NO_HOLDER)
        return _Resolution(open_session, ActivationOutcome.WOKEN, 1)
    if open_session is not None and await entitled_to_request(open_session.session_id, facts.slug, facts.request_key):
        return _Resolution(open_session, ActivationOutcome.WOKEN, 1)
    created = await _create_agent(
        cmd,
        activation,
        home,
        folder,
        cmd.attendance,
        subject=subject,
        own_row_only=True,
        initialization=initialization,
        single_claim=True,
    )
    return _Resolution(created, ActivationOutcome.STARTED, 0)


async def _settle_unassigned_backlog(activation: ProcedureEventRecord, folder: Path, session: Session) -> None:
    """Judge each unassigned row of the responsibility by the same two rules applied to its own event.

    A row that qualifies is the session's own and is assigned to it; a request for another key is ``stale request`` and a
    notice with no holder yet is ``no holder``. No row is ended as a blanket supersession of a backlog.
    """
    rows = await db.list_unassigned_responsibility_events(responsibility_key=activation.responsibility_key)
    for row in rows:
        if row.activation_id == activation.activation_id:
            continue
        facts = event_facts(row.event_json)
        reason = judge(facts, await _item_for_home(folder, facts), session.session_id if _is_open(session) else "")
        if reason is not None:
            await db.not_deliver_procedure_event(activation_id=row.activation_id, reason=reason.value)
        else:
            await db.assign_procedure_events_unless_closed(
                activation_ids=[row.activation_id],
                session_id=session.session_id,
                reason=NotDeliveredReason.SESSION_CLOSED.value,
            )


async def _resolve_subject_agent(
    cmd: ActivateProcedureCommand,
    activation: ProcedureEventRecord,
    home: ActivationHome,
    folder: Path,
    initialization: DriverInitialization,
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
    created = await _create_agent(
        cmd, activation, home, folder, cmd.attendance, subject=subject, initialization=initialization
    )
    return _Resolution(created, ActivationOutcome.STARTED, candidate_count)


async def activate(cmd: ActivateProcedureCommand) -> ProcedureActivationResult:
    """Wake, revive or start the procedure's agent for the home, then deliver the event.

    The agent is the home's one agent, or — for a procedure declaring subject
    identity — the agent bound to the event's subject. Raises on any failure —
    the home is absent on this computer, the procedure is not a usable entry procedure, create returned no
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
            initialization = driver_initialization(procedure_id)
            single_claim = cmd.identity is SubscriptionIdentity.SUBJECT and await _is_single_claim_activation(
                cmd, home, folder, initialization
            )
            if single_claim:
                decided = await _resolve_single_claim(cmd, activation, home, folder, initialization)
                if isinstance(decided, _NotDelivered):
                    await db.not_deliver_procedure_event(
                        activation_id=activation.activation_id, reason=decided.reason.value
                    )
                    logger.info(
                        _PROCEDURE_ACTIVATION_NOT_DELIVERED_EVENT,
                        procedure_id=procedure_id,
                        home=home.to_token(),
                        activation_id=activation.activation_id,
                        reason=decided.reason.value,
                    )
                    return {
                        "session_id": "",
                        "outcome": ActivationOutcome.NOT_DELIVERED,
                        "reason": decided.reason.value,
                    }
                resolution = decided
            elif cmd.identity is SubscriptionIdentity.SUBJECT:
                resolution = await _resolve_subject_agent(cmd, activation, home, folder, initialization)
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
        if single_claim:
            if resolution.outcome is not ActivationOutcome.STARTED:
                assigned = await db.assign_procedure_events_unless_closed(
                    activation_ids=[activation.activation_id],
                    session_id=resolution.session.session_id,
                    reason=NotDeliveredReason.SESSION_CLOSED.value,
                )
                if ProcedureEventDeliveryOutcome.NOT_DELIVERED in assigned:
                    return {
                        "session_id": "",
                        "outcome": ActivationOutcome.NOT_DELIVERED,
                        "reason": NotDeliveredReason.SESSION_CLOSED.value,
                    }
            await _settle_unassigned_backlog(activation, folder, resolution.session)
            await wake_procedure_events_if_pending(session_id=resolution.session.session_id)
        elif resolution.outcome is not ActivationOutcome.STARTED:
            await db.reassign_procedure_events(
                responsibility_key=activation.responsibility_key,
                session_id=resolution.session.session_id,
            )
            await wake_procedure_events_if_pending(session_id=resolution.session.session_id)

        operation_row = await db.get_operation_by_request(
            kind=OperationKind.PROCEDURE_ACTIVATION, caller_session_id=None, client_request_id=cmd.request_id or ""
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
