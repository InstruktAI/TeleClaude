"""Procedure entry: the one path from a named procedure to a launchable invocation.

Every agent assignment starts by naming a published procedure. This module resolves that procedure's
declared role, parameters and dispatch defaults before any session exists, checks the caller's dispatch
privilege, materializes the procedure's complete brief as one artifact and composes the loader that names
it (``local/projects/teleclaude/spec/feature/agent_runtime/procedure-entry``). An entry type adds typed
context and the required reads it implies; it never supplies a role of its own.
"""

from __future__ import annotations

import hashlib
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
from teleclaude.core.injected_text import render_command_loader
from teleclaude.core.models._session import NO_ADDITIONAL_CONTEXT, ProcedureEntryKind, ProcedureInvocation
from teleclaude.core.roles import Role, UnknownRole, may_dispatch
from teleclaude.docs_subscriptions import (
    ProcedureDeliverySettings,
    SubscriptionAttendance,
    required_event_handling_dependencies,
)
from teleclaude.entry_declarations import EntryDeclarations, ProcedureParameter
from teleclaude.helpers.agent_types import ThinkingMode
from teleclaude.paths import SESSION_BRIEF_FILENAME, SESSION_INLINE_BRIEF_FILENAME_PREFIX, session_tmp_dir

SCHEDULED_JOB_RUN_PROCEDURE_ID: Final = "general/procedure/scheduled-job-run"
SLUG_PARAMETER: Final = "slug"
FACT_JOB: Final = "job"
FACT_HOME: Final = "home"
FACT_SUBJECT: Final = "subject"
FACT_ATTENDANCE: Final = "attendance"
FACT_EVENT_DELIVERY: Final = "event_delivery"
FACT_INTERRUPTIBLE: Final = "interruptible"

_SEGMENT_SEPARATOR: Final = "/"
_SEGMENT_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_MIN_SEGMENTS: Final = 3
_INLINE_BRIEF_FILENAME_TEMPLATE: Final = SESSION_INLINE_BRIEF_FILENAME_PREFIX + "{digest}.md"
_INLINE_DIGEST_LENGTH: Final = 12
_INLINE_DIGEST_SEPARATOR: Final = "\0"
_UTF8: Final = "utf-8"
_ROLE_NAME_SEPARATOR: Final = "-"
_FRAMING_TEMPLATE: Final = "You are now the {role}."
_INPUTS_HEADING: Final = "## Provided inputs"
_INPUT_LINE_TEMPLATE: Final = "- {name}: {value}"
_CONTEXT_HEADING: Final = "## Entry context"
_CONTEXT_LINE_TEMPLATE: Final = "- {name}: {value}"
_ARGUMENTS_LINE_TEMPLATE: Final = "- $ARGUMENTS (the raw argument text): {arguments}"
_ADDITIONAL_CONTEXT_SECTION_TEMPLATE: Final = "ADDITIONAL CONTEXT:\n{context}"
_TOKEN_JOINER: Final = " "
_SECTION_SEPARATOR: Final = "\n\n"
_LINE_SEPARATOR: Final = "\n"
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
_BRIEF_UNWRITABLE_TEMPLATE: Final = "the brief for {procedure} cannot be materialized: {detail}"
_BAD_REQUEST_STATUS: Final = 400
_FORBIDDEN_STATUS: Final = 403
_UNAVAILABLE_STATUS: Final = 503


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
    brief states; an entry type's required reads are rendered into the brief beside the procedure's own
    closure.
    """

    kind: ProcedureEntryKind = ProcedureEntryKind.DIRECT
    job: str | None = None
    required_reads: tuple[str, ...] = ()
    agents: tuple[str, ...] | None = None
    thinking_mode: ThinkingMode | None = None
    facts: tuple[tuple[str, str], ...] = ()


def job_entry(job_name: str, agents: tuple[str, ...], thinking_mode: ThinkingMode) -> EntryContext:
    """The entry context of a scheduled job: its name, its declared dispatch and the close-out a job owes."""
    return EntryContext(
        kind=ProcedureEntryKind.JOB,
        job=job_name,
        required_reads=(SCHEDULED_JOB_RUN_PROCEDURE_ID,),
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
) -> EntryContext:
    """The entry context of an activation: the home, subject, attendance and delivery facts it carries and the
    event-handling instructions its delivery settings imply."""
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
        required_reads=required_event_handling_dependencies(delivery),
        facts=tuple(facts),
    )


def manual_activation_entry(*, procedure_id: str, home: str, required_reads: tuple[str, ...]) -> EntryContext:
    """The entry context of a standing agent started by hand for a home: attended, with the activation's reads."""
    return EntryContext(
        kind=ProcedureEntryKind.ACTIVATION,
        job=procedure_id,
        required_reads=required_reads,
        facts=((FACT_HOME, home), (FACT_ATTENDANCE, SubscriptionAttendance.ATTENDED.value)),
    )


@dataclass(frozen=True)
class ResolvedInvocation:
    """A procedure entry resolved far enough to create the session: role, brief, loader and dispatch defaults."""

    procedure_id: str
    role: Role
    arguments: str
    parameters: tuple[tuple[str, str], ...]
    working_slug: str | None
    entry: EntryContext
    brief_path: Path
    loader: str
    agents: tuple[str, ...]
    thinking_mode: ThinkingMode
    additional_context: str = NO_ADDITIONAL_CONTEXT

    @property
    def record(self) -> ProcedureInvocation:
        """The persisted form a continuation rebuilds the loader and the brief from, additional context included."""
        return ProcedureInvocation(
            procedure_id=self.procedure_id,
            arguments=self.arguments,
            parameters=self.parameters,
            entry_kind=self.entry.kind,
            entry_job=self.entry.job,
            entry_reads=self.entry.required_reads,
            brief_path=str(self.brief_path),
            entry_facts=self.entry.facts,
            additional_context=self.additional_context,
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
    """The line that opens a brief and presents the role by its assignment, nothing about its reach."""
    title = _TOKEN_JOINER.join(part.capitalize() for part in role.name.value.split(_ROLE_NAME_SEPARATOR))
    return _FRAMING_TEMPLATE.format(role=title)


def _compose_brief(
    role: Role | None,
    parameters: tuple[tuple[str, str], ...],
    arguments: str,
    facts: tuple[tuple[str, str], ...],
    closure: str,
    additional_context: str,
) -> str:
    """The role's framing line, the parameter preamble, the entry context, the procedure's closure and the
    additional context supplied at launch once, as one artifact.

    Creation and every continuation door render the brief through this one function over the same invocation
    record. An inline read inside an existing session states no role: that session keeps the one it has.
    """
    inputs = [_INPUT_LINE_TEMPLATE.format(name=name, value=value) for name, value in parameters]
    inputs.append(_ARGUMENTS_LINE_TEMPLATE.format(arguments=arguments))
    sections = [_LINE_SEPARATOR.join((_INPUTS_HEADING, *inputs))]
    if facts:
        context = [_CONTEXT_LINE_TEMPLATE.format(name=name, value=value) for name, value in facts]
        sections.append(_LINE_SEPARATOR.join((_CONTEXT_HEADING, *context)))
    sections.append(closure)
    if additional_context:
        sections.append(_ADDITIONAL_CONTEXT_SECTION_TEMPLATE.format(context=additional_context))
    if role is not None:
        sections.insert(0, framing_line(role))
    return _SECTION_SEPARATOR.join(sections)


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
    """One resolved publication of an entry procedure: its declarations and the strict closure selected beside them."""

    declarations: EntryDeclarations
    closure: str


def _published_entry(procedure_id: str, project_root: Path, entry_reads: tuple[str, ...]) -> PublishedEntry:
    """Select the procedure's strict closure from the published index and read its declarations from that root.

    The declarations come from the same index entry the closure is rooted at, so the role, parameters and
    dispatch defaults the entry acts on are the ones the brief is composed from; a gap refuses naming its cause.
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
        closure = build_context_output(
            areas=[],
            project_root=project_root,
            snippet_ids=[procedure_id],
            entry_closure=True,
            entry_reads=list(entry_reads),
            on_closure_root=admit,
            caller=SystemCliCaller(),
        )
    except ActivationClosureError as exc:
        raise EntryRefusal(
            status_code=_BAD_REQUEST_STATUS, detail=str(exc), reason=AgentDispatchReason.COMMAND_INVALID
        ) from exc
    if not declared:
        raise _gap_refusal(procedure_id, EntryGap.UNKNOWN)
    return PublishedEntry(declarations=declared[0], closure=closure)


def published_entry_declarations(procedure_id: str, project_root: Path) -> EntryDeclarations:
    """The declarations of a published, usable entry procedure, from the publication its closure is rooted at."""
    return _published_entry(procedure_id, project_root, ()).declarations


def _write_brief(
    *,
    procedure_id: str,
    brief_path: Path,
    closure: str,
    role: Role | None,
    parameters: tuple[tuple[str, str], ...],
    arguments: str,
    facts: tuple[tuple[str, str], ...],
    additional_context: str,
) -> Path:
    """Materialize the brief at ``brief_path`` from the entry's closure, the entry type's context and the additional context."""
    try:
        brief_path.parent.mkdir(parents=True, exist_ok=True)
        brief_path.write_text(
            _compose_brief(role, parameters, arguments, facts, closure, additional_context), encoding=_UTF8
        )
    except OSError as exc:
        raise EntryRefusal(
            status_code=_UNAVAILABLE_STATUS,
            detail=_BRIEF_UNWRITABLE_TEMPLATE.format(procedure=procedure_id, detail=exc),
            reason=AgentDispatchReason.COMMAND_INVALID,
        ) from exc
    return brief_path


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
    session_id: str,
    caller_mode: ThinkingMode | None,
    additional_context: str = NO_ADDITIONAL_CONTEXT,
) -> ResolvedInvocation:
    """Resolve a named procedure into the invocation its session is created from, or refuse before any side effect.

    The additional context supplied at launch is part of the resolved invocation: the brief renders it once
    and the persisted record carries it for every continuation.
    """
    procedure_id = normalize_procedure_id(procedure_token)
    published = _published_entry(procedure_id, project_root, entry.required_reads)
    declarations = published.declarations
    dispatch = declarations.dispatch
    if dispatch is None:
        raise _gap_refusal(procedure_id, EntryGap.NO_DISPATCH)
    parameters = bind_parameters(procedure_id, declarations.parameters, arguments)
    _check_dispatch_privilege(caller, declarations.role, procedure_id)
    agents = entry.agents or tuple(agent.value for agent in dispatch.agents)
    thinking_mode = caller_mode or entry.thinking_mode or dispatch.thinking_mode
    brief_path = _write_brief(
        procedure_id=procedure_id,
        brief_path=session_tmp_dir(session_id) / SESSION_BRIEF_FILENAME,
        closure=published.closure,
        role=declarations.role,
        parameters=parameters,
        arguments=arguments.strip(),
        facts=entry.facts,
        additional_context=additional_context,
    )
    return ResolvedInvocation(
        procedure_id=procedure_id,
        role=declarations.role,
        arguments=arguments.strip(),
        parameters=parameters,
        working_slug=dict(parameters).get(SLUG_PARAMETER),
        entry=entry,
        brief_path=brief_path,
        loader=render_command_loader(procedure_id, str(brief_path), arguments.strip()),
        agents=agents,
        thinking_mode=thinking_mode,
        additional_context=additional_context,
    )


@dataclass(frozen=True)
class InlineInvocation:
    """A procedure read into an existing session: the bound arguments, the brief it composed and the loader naming it."""

    procedure_id: str
    arguments: str
    working_slug: str | None
    brief_path: Path
    loader: str


def resolve_inline_entry(
    *, procedure_token: str, arguments: str, project_root: Path, session_id: str
) -> InlineInvocation:
    """Resolve a procedure named inside an existing session into a loader for it.

    The session keeps its role and authority: nothing is dispatched, no role is stated, and the brief is
    written beside the session's own so the one it launched with stays intact. The same input always names
    the same file, so a retried delivery wraps no second brief.
    """
    procedure_id = normalize_procedure_id(procedure_token)
    published = _published_entry(procedure_id, project_root, ())
    parameters = bind_parameters(procedure_id, published.declarations.parameters, arguments)
    text = arguments.strip()
    digest = hashlib.sha256(_INLINE_DIGEST_SEPARATOR.join((procedure_id, text)).encode(_UTF8)).hexdigest()
    brief_path = _write_brief(
        procedure_id=procedure_id,
        brief_path=session_tmp_dir(session_id)
        / _INLINE_BRIEF_FILENAME_TEMPLATE.format(digest=digest[:_INLINE_DIGEST_LENGTH]),
        closure=published.closure,
        role=None,
        parameters=parameters,
        arguments=text,
        facts=(),
        additional_context=NO_ADDITIONAL_CONTEXT,
    )
    return InlineInvocation(
        procedure_id=procedure_id,
        arguments=text,
        working_slug=dict(parameters).get(SLUG_PARAMETER),
        brief_path=brief_path,
        loader=render_command_loader(procedure_id, str(brief_path), text),
    )


@dataclass(frozen=True)
class RebuiltInvocation:
    """A persisted invocation re-materialized for a continuation: the brief it names and the loader for it."""

    procedure_id: str
    brief_path: Path
    loader: str


def rematerialize_invocation(
    *, invocation: ProcedureInvocation, role: Role | None, project_root: Path
) -> RebuiltInvocation:
    """Rebuild the brief a persisted invocation named, keeping the role the session carries.

    The procedure must still be a usable entry procedure; the parameters, argument text, entry context and
    entry reads and additional context are those persisted at creation, never rebound or re-derived.
    """
    published = _published_entry(invocation.procedure_id, project_root, invocation.entry_reads)
    brief_path = _write_brief(
        procedure_id=invocation.procedure_id,
        brief_path=Path(invocation.brief_path),
        closure=published.closure,
        role=role,
        parameters=invocation.parameters,
        arguments=invocation.arguments,
        facts=invocation.entry_facts,
        additional_context=invocation.additional_context,
    )
    return RebuiltInvocation(
        procedure_id=invocation.procedure_id,
        brief_path=brief_path,
        loader=render_command_loader(invocation.procedure_id, str(brief_path), invocation.arguments),
    )
