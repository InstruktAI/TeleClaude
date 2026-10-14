"""Continuation of a procedure session: restart, revival and handoff rebuild its loader from the resolved invocation.

A session started through a procedure entry persists its resolved invocation on its launch state; every
continuation door rebuilds the reference loader and keeps the role the session carries. A session recorded
before procedure entry has no persisted invocation: it is reconstructed from the evidence its row retained,
exactly as ``local/projects/teleclaude/spec/feature/agent_runtime/session-role-migration`` states it — the
migrated command is the procedure, the working slug the ``slug`` parameter, the job the entry context, and
the delivery settings and subject binding the activation's. A required input the row does not retain is never
invented: the continuation is refused naming it, and the row keeps the role it has.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.core.models import Session, SessionEntryPoint, SessionLaunchIntent
from teleclaude.core.models._adapter import session_is_unattended
from teleclaude.core.models._session import ProcedureEntryKind, ProcedureInvocation
from teleclaude.core.procedure_entry import (
    FACT_ATTENDANCE,
    FACT_EVENT_DELIVERY,
    FACT_HOME,
    FACT_INTERRUPTIBLE,
    FACT_JOB,
    FACT_SUBJECT,
    SLUG_PARAMETER,
    EntryRefusal,
    published_entry_declarations,
    rebuild_invocation_loader,
)
from teleclaude.core.procedure_event_delivery import procedure_responsibility_parts
from teleclaude.core.roles import Role, UnknownRole, resolve_role
from teleclaude.docs_subscriptions import ProcedureDeliverySettings, SubscriptionAttendance
from teleclaude.paths import REPO_ROOT
from teleclaude.types.procedure_delivery import BINDING_SECTION, BindingField

logger = get_logger(__name__)

_CONTINUATION_REFUSED_EVENT: Final = "session_continuation_refused"
_ARGUMENT_JOINER: Final = " "
_UNKNOWN_ROLE_TEMPLATE: Final = "the session carries the role '{role}', which the catalog does not name"
_MISSING_INPUT_TEMPLATE: Final = "the session's row retains no {missing}, which {procedure} requires"
_MISSING_PARAMETER: Final = "value for the parameter '{name}'"
_MISSING_JOB: Final = "job name"
_MISSING_DELIVERY: Final = "activation delivery settings"
_MISSING_HOME: Final = "activation home"
_TRUE: Final = "true"
_FALSE: Final = "false"


class ContinuationRefused(RuntimeError):
    """A continuation cannot rebuild its loader; the detail names the missing input or the unusable procedure."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class ContinuationLoader:
    """The reference loader a continuation hands the relaunched agent."""

    procedure_id: str
    loader: str


def _project_root(session: Session) -> Path:
    return Path(session.project_path) if session.project_path else REPO_ROOT


def _reconstructed_parameters(session: Session, procedure_id: str) -> tuple[tuple[str, str], ...]:
    """Bind the parameters the row retains: the working slug as ``slug``, then declared defaults.

    A required parameter the row does not retain (a research brief, a commit list) refuses the
    continuation naming it.
    """
    declarations = published_entry_declarations(procedure_id, _project_root(session))
    bound: list[tuple[str, str]] = []
    for parameter in declarations.parameters:
        if parameter.name == SLUG_PARAMETER and session.working_slug:
            bound.append((parameter.name, session.working_slug))
        elif parameter.default is not None:
            bound.append((parameter.name, parameter.default))
        elif parameter.required:
            raise ContinuationRefused(
                _MISSING_INPUT_TEMPLATE.format(
                    missing=_MISSING_PARAMETER.format(name=parameter.name), procedure=procedure_id
                )
            )
    return tuple(bound)


def _entry_kind(session: Session, intent: SessionLaunchIntent | None) -> ProcedureEntryKind:
    """The entry type the row retains: the launch's entry point, else the shape of its job field."""
    entry_point = intent.entry_point if intent is not None else None
    if entry_point is SessionEntryPoint.CRON:
        return ProcedureEntryKind.JOB
    if entry_point is SessionEntryPoint.PROCEDURE_ACTIVATION:
        return ProcedureEntryKind.ACTIVATION
    if entry_point is None and session.job:
        return ProcedureEntryKind.ACTIVATION if session.job == session.command else ProcedureEntryKind.JOB
    return ProcedureEntryKind.DIRECT


async def _activation_context(session: Session, procedure_id: str) -> tuple[tuple[str, str], ...]:
    """The activation facts the row retains: delivery settings, home and subject binding."""
    delivery = await db.get_procedure_delivery_session(session_id=session.session_id)
    if delivery is None:
        raise ContinuationRefused(_MISSING_INPUT_TEMPLATE.format(missing=_MISSING_DELIVERY, procedure=procedure_id))
    _, home, subject = procedure_responsibility_parts(delivery.responsibility_key)
    binding = session.get_origin_section(BINDING_SECTION)
    bound_subject = binding.get(BindingField.SUBJECT.value)
    subject = bound_subject if isinstance(bound_subject, str) else subject
    settings = ProcedureDeliverySettings(event_delivery=delivery.event_delivery, interruptible=delivery.interruptible)
    attendance = (
        SubscriptionAttendance.UNATTENDED if session_is_unattended(session) else SubscriptionAttendance.ATTENDED
    )
    facts = [(FACT_HOME, home)]
    if subject is not None:
        facts.append((FACT_SUBJECT, subject))
    facts.extend(
        (
            (FACT_ATTENDANCE, attendance.value),
            (FACT_EVENT_DELIVERY, settings.event_delivery.value),
            (FACT_INTERRUPTIBLE, _TRUE if settings.interruptible else _FALSE),
        )
    )
    return tuple(facts)


async def reconstruct_invocation(session: Session, intent: SessionLaunchIntent | None) -> ProcedureInvocation:
    """Rebuild the invocation of a session recorded before procedure entry from the evidence its row retains."""
    procedure_id = session.command
    if not procedure_id:
        raise ContinuationRefused(_MISSING_INPUT_TEMPLATE.format(missing=_MISSING_JOB, procedure=""))
    parameters = _reconstructed_parameters(session, procedure_id)
    kind = _entry_kind(session, intent)
    facts: tuple[tuple[str, str], ...] = ()
    job: str | None = None
    if kind is ProcedureEntryKind.JOB:
        if not session.job:
            raise ContinuationRefused(_MISSING_INPUT_TEMPLATE.format(missing=_MISSING_JOB, procedure=procedure_id))
        job = session.job
        facts = ((FACT_JOB, job),)
    elif kind is ProcedureEntryKind.ACTIVATION:
        job = session.job or procedure_id
        facts = await _activation_context(session, procedure_id)
    return ProcedureInvocation(
        procedure_id=procedure_id,
        arguments=_ARGUMENT_JOINER.join(value for _, value in parameters),
        parameters=parameters,
        entry_kind=kind,
        entry_job=job,
        entry_facts=facts,
    )


async def rebuild_continuation_loader(session: Session) -> ContinuationLoader | None:
    """Rebuild the reference loader a session was started with.

    ``None`` for a session started without a procedure. The stored role is kept: a role the catalog does
    not name refuses the continuation, as does a procedure that is no longer a usable entry procedure or an
    input the row does not retain — each refusal is logged naming the cause and leaves the row untouched.
    """
    handover = await db.get_startup_handover(session.session_id)
    intent = handover.intent if handover is not None else None
    stored = intent.invocation if intent is not None else None
    if stored is None and not session.command:
        return None
    try:
        role = resolve_role(session.role)
        if isinstance(role, UnknownRole):
            raise ContinuationRefused(_UNKNOWN_ROLE_TEMPLATE.format(role=role.recorded))
        invocation = stored if stored is not None else await reconstruct_invocation(session, intent)
        rebuilt = rebuild_invocation_loader(
            invocation=invocation, role=role if isinstance(role, Role) else None, project_root=_project_root(session)
        )
    except EntryRefusal as exc:
        refusal = ContinuationRefused(exc.detail)
        logger.error(_CONTINUATION_REFUSED_EVENT, session_id=session.session_id, detail=refusal.detail)
        raise refusal from exc
    except ContinuationRefused as exc:
        logger.error(_CONTINUATION_REFUSED_EVENT, session_id=session.session_id, detail=exc.detail)
        raise
    return ContinuationLoader(procedure_id=rebuilt.procedure_id, loader=rebuilt.loader)
