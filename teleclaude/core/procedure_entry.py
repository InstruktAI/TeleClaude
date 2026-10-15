"""Procedure entry: the one path from a named procedure to a launchable invocation.

Every agent assignment starts by naming a published procedure. This module resolves that procedure's
declared role, parameters and dispatch defaults before any session exists, checks the caller's dispatch
privilege, and composes a short loader that points at the procedure's published closure
(``local/projects/teleclaude/spec/feature/agent_runtime/procedure-entry``). An entry type adds typed facts;
it never supplies a role or documentation reads of its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from teleclaude.caller_identity import SystemCliCaller
from teleclaude.context_selector import (
    ActivationClosureError,
    EntryGap,
    SnippetMeta,
    build_context_output,
    entry_procedure_gap,
)
from teleclaude.core.agent_dispatch import AgentDispatchReason
from teleclaude.core.injected_text import render_reference_loader
from teleclaude.core.models._session import (
    NO_ADDITIONAL_CONTEXT,
    NO_WORKFLOW_PUBLICATION,
    ProcedureEntryKind,
    ProcedureInvocation,
)
from teleclaude.core.roles import Role, UnknownRole, may_dispatch
from teleclaude.docs_subscriptions import (
    ProcedureDeliverySettings,
    SubscriptionAttendance,
)
from teleclaude.entry_declarations import EntryDeclarations, ProcedureParameter
from teleclaude.helpers.agent_types import ThinkingMode
from teleclaude.types.work_subject import WorkSubjectParameter

SLUG_PARAMETER: Final = WorkSubjectParameter.SLUG.value
FACT_JOB: Final = "job"
FACT_HOME: Final = "home"
FACT_SUBJECT: Final = "subject"
FACT_ATTENDANCE: Final = "attendance"
FACT_EVENT_DELIVERY: Final = "event_delivery"
FACT_INTERRUPTIBLE: Final = "interruptible"

_SEGMENT_SEPARATOR: Final = "/"
_SEGMENT_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_MIN_SEGMENTS: Final = 3
_ROLE_NAME_SEPARATOR: Final = "-"
_TOKEN_JOINER: Final = " "
_FRAMING_TEMPLATE: Final = "You are now the {role}."
_ADDITIONAL_CONTEXT_SECTION_TEMPLATE: Final = "ADDITIONAL CONTEXT:\n{context}"
_SECTION_SEPARATOR: Final = "\n\n"
_UNKNOWN_COMMAND_TEMPLATE: Final = (
    "unknown command: {token}; a session is started by naming a published procedure by its domain-qualified snippet ID"
)
_PROCEDURE_GAP_TEMPLATE: Final = "{procedure} is not a usable entry procedure: {cause}"
_NO_PARAMETERS_TEMPLATE: Final = "{procedure} takes no arguments"
_SURPLUS_TEMPLATE: Final = "{procedure} takes {count} argument(s); surplus: {surplus}"
_MISSING_PARAMETER_TEMPLATE: Final = "{procedure} requires the parameter '{name}'"
_DISPATCH_PRIVILEGE_TEMPLATE: Final = (
    "role '{caller}' cannot dispatch {procedure} (requires dispatch privilege for '{target}')"
)
_BAD_REQUEST_STATUS: Final = 400
_FORBIDDEN_STATUS: Final = 403


class EntryRefusal(ValueError):
    """A procedure entry refused before any session exists, with the cause and its dispatch reason."""

    def __init__(self, *, status_code: int, detail: str, reason: AgentDispatchReason) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.reason = reason


@dataclass(frozen=True)
class EntryContext:
    """What the entry type supplies beside the arguments.

    A job entry carries the job's name and its declaration's candidate order and thinking mode; an
    activation entry carries its home, subject, attendance and delivery facts. ``job`` is the session's
    instance identity (a job's name, an activation's procedure ID); ``facts`` are the named context lines the
    loader states. Procedure reads are owned by the procedure's declaration.
    """

    kind: ProcedureEntryKind = ProcedureEntryKind.DIRECT
    job: str | None = None
    agents: tuple[str, ...] | None = None
    thinking_mode: ThinkingMode | None = None
    facts: tuple[tuple[str, str], ...] = ()
    workflow_publication: str = NO_WORKFLOW_PUBLICATION


def job_entry(job_name: str, agents: tuple[str, ...], thinking_mode: ThinkingMode) -> EntryContext:
    """The entry context of a scheduled job: its name and declared dispatch."""
    return EntryContext(
        kind=ProcedureEntryKind.JOB,
        job=job_name,
        agents=agents,
        thinking_mode=thinking_mode,
        facts=((FACT_JOB, job_name),),
    )


def activation_entry(
    *,
    procedure_id: str,
    home: str,
    subject: str | None,
    attendance: SubscriptionAttendance,
    delivery: ProcedureDeliverySettings,
    workflow_publication: str = NO_WORKFLOW_PUBLICATION,
) -> EntryContext:
    """The entry context of an activation: the home, subject, attendance and delivery facts it carries.

    A lifecycle driver's activation also carries the workflow publication the driver is initialized under.
    """
    facts = [(FACT_HOME, home)]
    if subject is not None:
        facts.append((FACT_SUBJECT, subject))
    facts.extend(
        (
            (FACT_ATTENDANCE, attendance.value),
            (FACT_EVENT_DELIVERY, delivery.event_delivery.value),
            (FACT_INTERRUPTIBLE, str(delivery.interruptible).lower()),
        )
    )
    return EntryContext(
        kind=ProcedureEntryKind.ACTIVATION,
        job=procedure_id,
        facts=tuple(facts),
        workflow_publication=workflow_publication,
    )


def manual_activation_entry(*, procedure_id: str, home: str) -> EntryContext:
    """The entry context of a standing agent started by hand for a home."""
    return EntryContext(
        kind=ProcedureEntryKind.ACTIVATION,
        job=procedure_id,
        facts=(
            (FACT_HOME, home),
            (FACT_ATTENDANCE, SubscriptionAttendance.ATTENDED.value),
        ),
    )


@dataclass(frozen=True)
class ResolvedInvocation:
    """A procedure entry resolved far enough to create the session: role, loader and dispatch defaults."""

    procedure_id: str
    role: Role
    arguments: str
    parameters: tuple[tuple[str, str], ...]
    working_slug: str | None
    entry: EntryContext
    loader: str
    agents: tuple[str, ...]
    thinking_mode: ThinkingMode
    additional_context: str = NO_ADDITIONAL_CONTEXT

    @property
    def record(self) -> ProcedureInvocation:
        """The persisted invocation used to rebuild a continuation loader."""
        return ProcedureInvocation(
            procedure_id=self.procedure_id,
            arguments=self.arguments,
            parameters=self.parameters,
            entry_kind=self.entry.kind,
            entry_job=self.entry.job,
            entry_facts=self.entry.facts,
            additional_context=self.additional_context,
            workflow_publication=self.entry.workflow_publication,
        )


def normalize_procedure_id(token: str) -> str:
    """Validate a named procedure as a safe, domain-qualified snippet ID; a leading slash is tolerated.

    Anything shorter than a domain-qualified ID names no procedure — a retired command name included —
    and is refused before any publication read.
    """
    candidate = token.strip().removeprefix(_SEGMENT_SEPARATOR)
    segments = candidate.split(_SEGMENT_SEPARATOR)
    if len(segments) < _MIN_SEGMENTS or not all(_SEGMENT_PATTERN.fullmatch(segment) for segment in segments):
        raise EntryRefusal(
            status_code=_BAD_REQUEST_STATUS,
            detail=_UNKNOWN_COMMAND_TEMPLATE.format(token=token),
            reason=AgentDispatchReason.COMMAND_INVALID,
        )
    return candidate


def bind_parameters(
    procedure_id: str, parameters: tuple[ProcedureParameter, ...], arguments: str
) -> tuple[tuple[str, str], ...]:
    """Bind the raw argument text to the declared parameters once.

    Whitespace tokens bind to the positional entries in order, the untokenized remainder to a ``rest``
    entry, defaults fill omitted optional entries; a missing required entry or a surplus token refuses.
    """
    text = arguments.strip()
    if not parameters:
        if text:
            raise _parameter_refusal(_NO_PARAMETERS_TEMPLATE.format(procedure=procedure_id))
        return ()
    positional = [parameter for parameter in parameters if not parameter.rest]
    rest = next((parameter for parameter in parameters if parameter.rest), None)
    tokens = text.split(None, len(positional)) if rest is not None else text.split()
    if rest is None and len(tokens) > len(positional):
        raise _parameter_refusal(
            _SURPLUS_TEMPLATE.format(
                procedure=procedure_id, count=len(positional), surplus=_TOKEN_JOINER.join(tokens[len(positional) :])
            )
        )
    bound: list[tuple[str, str]] = []
    for index, parameter in enumerate(parameters):
        value = tokens[index] if index < len(tokens) else None
        if value is None:
            if parameter.required:
                raise _parameter_refusal(
                    _MISSING_PARAMETER_TEMPLATE.format(procedure=procedure_id, name=parameter.name)
                )
            value = parameter.default
        if value is not None:
            bound.append((parameter.name, value))
    return tuple(bound)


def _parameter_refusal(detail: str) -> EntryRefusal:
    return EntryRefusal(status_code=_BAD_REQUEST_STATUS, detail=detail, reason=AgentDispatchReason.SLUG_REQUIRED)


def framing_line(role: Role) -> str:
    """The loader's role line, presenting the assignment without describing its reach."""
    title = _TOKEN_JOINER.join(part.capitalize() for part in role.name.value.split(_ROLE_NAME_SEPARATOR))
    return _FRAMING_TEMPLATE.format(role=title)


def with_additional_context(text: str, additional_context: str) -> str:
    """``text`` followed by the additional context under its header, or ``text`` unchanged when there is none."""
    if not additional_context:
        return text
    return _SECTION_SEPARATOR.join((text, _ADDITIONAL_CONTEXT_SECTION_TEMPLATE.format(context=additional_context)))


def _check_dispatch_privilege(caller: Role | UnknownRole | None, target: Role, procedure_id: str) -> None:
    """Refuse a caller whose role holds neither full reach nor a dispatch grant covering the target's class."""
    if isinstance(caller, UnknownRole) or not may_dispatch(caller, target):
        recorded = caller.recorded if isinstance(caller, UnknownRole) else caller.name.value if caller else None
        raise EntryRefusal(
            status_code=_FORBIDDEN_STATUS,
            detail=_DISPATCH_PRIVILEGE_TEMPLATE.format(
                caller=recorded, procedure=procedure_id, target=target.name.value
            ),
            reason=AgentDispatchReason.DISPATCH_PRIVILEGE_FORBIDDEN,
        )


@dataclass(frozen=True)
class PublishedEntry:
    """The declarations from the publication that supplied an entry procedure's validated closure."""

    declarations: EntryDeclarations


def _published_entry(procedure_id: str, project_root: Path) -> PublishedEntry:
    """Select the procedure's strict closure from the published index and read its declarations from that root.

    The declarations come from the same index entry the closure is rooted at, so the role, parameters and
    dispatch defaults are read from the publication the loader names; a gap refuses naming its cause.
    """
    declared: list[EntryDeclarations] = []

    def admit(root: SnippetMeta | None) -> None:
        gap = entry_procedure_gap(root)
        if gap is not None:
            raise _gap_refusal(procedure_id, gap)
        declarations = root.entry.declarations if root is not None else None
        if declarations is None:
            raise _gap_refusal(procedure_id, EntryGap.NO_ROLE)
        declared.append(declarations)

    try:
        build_context_output(
            areas=[],
            project_root=project_root,
            snippet_ids=[procedure_id],
            entry_closure=True,
            on_closure_root=admit,
            caller=SystemCliCaller(),
        )
    except ActivationClosureError as exc:
        raise EntryRefusal(
            status_code=_BAD_REQUEST_STATUS, detail=str(exc), reason=AgentDispatchReason.COMMAND_INVALID
        ) from exc
    if not declared:
        raise _gap_refusal(procedure_id, EntryGap.UNKNOWN)
    return PublishedEntry(declarations=declared[0])


def published_entry_declarations(procedure_id: str, project_root: Path) -> EntryDeclarations:
    """The declarations of a published, usable entry procedure, from the publication its closure is rooted at."""
    return _published_entry(procedure_id, project_root).declarations


def _gap_refusal(procedure_id: str, gap: EntryGap) -> EntryRefusal:
    return EntryRefusal(
        status_code=_BAD_REQUEST_STATUS,
        detail=_PROCEDURE_GAP_TEMPLATE.format(procedure=procedure_id, cause=gap.value),
        reason=AgentDispatchReason.COMMAND_INVALID,
    )


def resolve_entry(
    *,
    procedure_token: str,
    arguments: str,
    project_root: Path,
    caller: Role | UnknownRole | None,
    entry: EntryContext,
    caller_mode: ThinkingMode | None,
    additional_context: str = NO_ADDITIONAL_CONTEXT,
    pinned: EntryDeclarations | None = None,
) -> ResolvedInvocation:
    """Resolve a named procedure into the invocation its session is created from, or refuse before any side effect.

    The additional context supplied at launch is part of the resolved invocation and loader.
    """
    procedure_id = normalize_procedure_id(procedure_token)
    published = _published_entry(procedure_id, project_root)
    declarations = pinned if pinned is not None else published.declarations
    dispatch = declarations.dispatch
    if dispatch is None:
        raise _gap_refusal(procedure_id, EntryGap.NO_DISPATCH)
    parameters = bind_parameters(procedure_id, declarations.parameters, arguments)
    _check_dispatch_privilege(caller, declarations.role, procedure_id)
    agents = entry.agents or tuple(agent.value for agent in dispatch.agents)
    thinking_mode = caller_mode or entry.thinking_mode or dispatch.thinking_mode
    return ResolvedInvocation(
        procedure_id=procedure_id,
        role=declarations.role,
        arguments=arguments.strip(),
        parameters=parameters,
        working_slug=dict(parameters).get(SLUG_PARAMETER),
        entry=entry,
        loader=render_reference_loader(
            procedure_id,
            framing_line(declarations.role),
            arguments.strip(),
            dict(parameters),
            dict(entry.facts),
            additional_context,
        ),
        agents=agents,
        thinking_mode=thinking_mode,
        additional_context=additional_context,
    )


@dataclass(frozen=True)
class InlineInvocation:
    """A procedure read into an existing session: its bound arguments and reference loader."""

    procedure_id: str
    arguments: str
    working_slug: str | None
    loader: str


def resolve_inline_entry(*, procedure_token: str, arguments: str, project_root: Path) -> InlineInvocation:
    """Resolve a procedure named inside an existing session into a loader for it.

    The session keeps its role and authority: nothing is dispatched and no role is stated.
    """
    procedure_id = normalize_procedure_id(procedure_token)
    published = _published_entry(procedure_id, project_root)
    parameters = bind_parameters(procedure_id, published.declarations.parameters, arguments)
    text = arguments.strip()
    return InlineInvocation(
        procedure_id=procedure_id,
        arguments=text,
        working_slug=dict(parameters).get(SLUG_PARAMETER),
        loader=render_reference_loader(procedure_id, None, text, dict(parameters), {}, NO_ADDITIONAL_CONTEXT),
    )


@dataclass(frozen=True)
class RebuiltInvocation:
    """A persisted invocation rebuilt for a continuation as a reference loader."""

    procedure_id: str
    loader: str


def rebuild_invocation_loader(
    *, invocation: ProcedureInvocation, role: Role | None, project_root: Path
) -> RebuiltInvocation:
    """Rebuild a persisted invocation's loader, keeping the role the session carries.

    The procedure must still be a usable entry procedure; the parameters, argument text, entry facts and
    additional context are those persisted at creation, never rebound or re-derived.
    """
    _published_entry(invocation.procedure_id, project_root)
    role_framing = framing_line(role) if role is not None else None
    return RebuiltInvocation(
        procedure_id=invocation.procedure_id,
        loader=render_reference_loader(
            invocation.procedure_id,
            role_framing,
            invocation.arguments,
            dict(invocation.parameters),
            dict(invocation.entry_facts),
            invocation.additional_context,
        ),
    )
