"""A procedure's entry declarations: the role, parameters and dispatch defaults it carries as a launch root.

One reader serves validation, index publication and snippet metadata, so every consumer sees the same
shape (``general/spec/snippet-authoring-schema``). The reader reports findings and never raises; a
declaration carrying findings is not a usable entry.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import NotRequired, TypedDict

from teleclaude.agent_registry import AgentName
from teleclaude.core.roles import Role, resolve_role
from teleclaude.core.workflow_machine.vocabulary import ENDING_ACT_RULES, HELD_PHASE
from teleclaude.helpers.agent_types import ThinkingMode
from teleclaude.types.workflow_record import Act, DrivenPhase, Phase


class EntryKey(StrEnum):
    """The frontmatter and published-index keys carrying a procedure's entry declarations."""

    ROLE = "role"
    PARAMETERS = "parameters"
    DISPATCH = "dispatch"
    WORKFLOW = "workflow"


class WorkflowKey(StrEnum):
    """The keys of a driver procedure's workflow declaration."""

    DRIVES = "drives"
    CHILD = "child"
    ACTS = "acts"
    SCOPES = "scopes"
    SESSION = "session"


class ScopeKey(StrEnum):
    """The keys of one scope that narrows a driven phase's child and ending acts."""

    PHASE = "phase"
    CHILD = "child"
    ACTS = "acts"


class SessionMode(StrEnum):
    """How a driver procedure's sessions serve claims; the one value is a session that serves one claim of one item."""

    SINGLE_CLAIM = "single-claim"


class EndingActKey(StrEnum):
    """The keys of one act that ends the driver's phase."""

    ACT = "act"
    LEADS_TO = "leads_to"


class ParameterKey(StrEnum):
    """The keys of one declared parameter."""

    NAME = "name"
    REQUIRED = "required"
    DEFAULT = "default"
    REST = "rest"


class DispatchKey(StrEnum):
    """The keys of the dispatch defaults."""

    AGENT = "agent"
    THINKING_MODE = "thinking_mode"


class EntryFinding(StrEnum):
    """The finding codes a malformed entry declaration produces."""

    ROLE_INVALID_VALUE = "snippet_role_invalid_value"
    ROLE_UNKNOWN = "snippet_role_unknown"
    PARAMETERS_INVALID_VALUE = "snippet_parameters_invalid_value"
    PARAMETERS_DUPLICATE_NAME = "snippet_parameters_duplicate_name"
    PARAMETERS_REST_NOT_LAST = "snippet_parameters_rest_not_last"
    PARAMETERS_DEFAULT_INVALID = "snippet_parameters_default_invalid"
    PARAMETERS_DEFAULT_ON_REQUIRED = "snippet_parameters_default_on_required"
    PARAMETERS_WITHOUT_ROLE = "snippet_parameters_without_role"
    DISPATCH_INVALID_VALUE = "snippet_dispatch_invalid_value"
    DISPATCH_AGENT_EMPTY = "snippet_dispatch_agent_empty"
    DISPATCH_AGENT_UNKNOWN = "snippet_dispatch_agent_unknown"
    DISPATCH_MODE_UNKNOWN = "snippet_dispatch_mode_unknown"
    DISPATCH_WITHOUT_ROLE = "snippet_dispatch_without_role"
    WORKFLOW_INVALID_VALUE = "snippet_workflow_invalid_value"
    WORKFLOW_DRIVES_EMPTY = "snippet_workflow_drives_empty"
    WORKFLOW_PHASE_UNKNOWN = "snippet_workflow_phase_unknown"
    WORKFLOW_PHASE_DUPLICATE = "snippet_workflow_phase_duplicate"
    WORKFLOW_CHILD_MISSING = "snippet_workflow_child_missing"
    WORKFLOW_ACTS_EMPTY = "snippet_workflow_acts_empty"
    WORKFLOW_ACT_UNKNOWN = "snippet_workflow_act_unknown"
    WORKFLOW_ACT_DUPLICATE = "snippet_workflow_act_duplicate"
    WORKFLOW_LEADS_TO_UNKNOWN = "snippet_workflow_leads_to_unknown"
    WORKFLOW_WITHOUT_ROLE = "snippet_workflow_without_role"
    WORKFLOW_SCOPE_INVALID = "snippet_workflow_scope_invalid"
    WORKFLOW_SCOPE_PHASE_NOT_DRIVEN = "snippet_workflow_scope_phase_not_driven"
    WORKFLOW_SCOPE_DUPLICATE = "snippet_workflow_scope_duplicate"
    WORKFLOW_PHASE_UNCOVERED = "snippet_workflow_phase_uncovered"
    WORKFLOW_SESSION_UNKNOWN = "snippet_workflow_session_unknown"
    WORKFLOW_ACT_NOT_ADMISSIBLE = "snippet_workflow_act_not_admissible"
    WORKFLOW_LEADS_TO_MISMATCH = "snippet_workflow_leads_to_mismatch"


#: The thinking modes a procedure's dispatch defaults may declare.
DECLARABLE_THINKING_MODES = (ThinkingMode.FAST, ThinkingMode.MED, ThinkingMode.SLOW)


@dataclass(frozen=True)
class EntryFindingDetail:
    """One finding: its code and the declared value it concerns."""

    code: EntryFinding
    value: str = ""


@dataclass(frozen=True)
class ProcedureParameter:
    """One declared launch argument."""

    name: str
    required: bool
    default: str | None
    rest: bool


@dataclass(frozen=True)
class DispatchDeclaration:
    """The procedure's launch defaults: an ordered agent preference list and a thinking mode."""

    agents: tuple[AgentName, ...]
    thinking_mode: ThinkingMode


@dataclass(frozen=True)
class EndingAct:
    """An act that ends the driver's phase, and the phase it leads to."""

    act: Act
    leads_to: Phase


@dataclass(frozen=True)
class WorkflowScope:
    """The child and ending acts of one driven phase; a scope with no child dispatches none."""

    phase: DrivenPhase
    child: str | None
    acts: tuple[EndingAct, ...]


@dataclass(frozen=True)
class WorkflowDeclaration:
    """A driver procedure's part in the item lifecycle: the phases it drives, the child it dispatches and its ending acts.

    ``child`` and ``acts`` are the defaults of every driven phase that has no scope of its own.
    """

    drives: tuple[DrivenPhase, ...]
    child: str | None
    acts: tuple[EndingAct, ...]
    scopes: tuple[WorkflowScope, ...] = ()
    session: SessionMode | None = None

    def scope_for(self, phase: DrivenPhase) -> WorkflowScope | None:
        """The scope declared for a driven phase, if any."""
        return next((scope for scope in self.scopes if scope.phase is phase), None)

    def child_for(self, phase: DrivenPhase) -> str | None:
        """The child procedure the driver of this phase dispatches; None when its scope names none."""
        scope = self.scope_for(phase)
        return scope.child if scope is not None else self.child

    def acts_for(self, phase: DrivenPhase) -> tuple[EndingAct, ...]:
        """The ending acts of this phase."""
        scope = self.scope_for(phase)
        return scope.acts if scope is not None else self.acts


@dataclass(frozen=True)
class EntryDeclarations:
    """What a procedure declares as a launch root. ``dispatch`` and ``workflow`` are ``None`` when undeclared."""

    role: Role
    parameters: tuple[ProcedureParameter, ...]
    dispatch: DispatchDeclaration | None
    workflow: WorkflowDeclaration | None = None


@dataclass(frozen=True)
class EntryParse:
    """The result of reading a snippet's entry declarations."""

    declarations: EntryDeclarations | None
    findings: tuple[EntryFindingDetail, ...]
    declares_entry_fields: bool


#: The parse of a snippet that carries none of the entry declaration keys.
NO_ENTRY_DECLARATIONS = EntryParse(declarations=None, findings=(), declares_entry_fields=False)


def declares_entry_fields(metadata: Mapping[str, object]) -> bool:
    """Whether the metadata carries any of the entry declaration keys."""
    return any(key.value in metadata for key in EntryKey)


def _parse_parameters(raw: object) -> tuple[tuple[ProcedureParameter, ...], list[EntryFindingDetail]]:
    findings: list[EntryFindingDetail] = []
    if not isinstance(raw, list):
        return (), [EntryFindingDetail(EntryFinding.PARAMETERS_INVALID_VALUE)]
    parameters: list[ProcedureParameter] = []
    seen: set[str] = set()
    known_keys = {key.value for key in ParameterKey}
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping) or not set(item) <= known_keys:
            findings.append(EntryFindingDetail(EntryFinding.PARAMETERS_INVALID_VALUE, str(index)))
            continue
        name = item.get(ParameterKey.NAME)
        required = item.get(ParameterKey.REQUIRED, False)
        default = item.get(ParameterKey.DEFAULT)
        rest = item.get(ParameterKey.REST, False)
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(required, bool)
            or not isinstance(rest, bool)
        ):
            findings.append(EntryFindingDetail(EntryFinding.PARAMETERS_INVALID_VALUE, str(index)))
            continue
        if name in seen:
            findings.append(EntryFindingDetail(EntryFinding.PARAMETERS_DUPLICATE_NAME, name))
        seen.add(name)
        if default is not None and not isinstance(default, str):
            findings.append(EntryFindingDetail(EntryFinding.PARAMETERS_DEFAULT_INVALID, name))
            default = None
        elif default is not None and required:
            findings.append(EntryFindingDetail(EntryFinding.PARAMETERS_DEFAULT_ON_REQUIRED, name))
        parameters.append(ProcedureParameter(name=name, required=required, default=default, rest=rest))
    for index, parameter in enumerate(parameters):
        if parameter.rest and index != len(parameters) - 1:
            findings.append(EntryFindingDetail(EntryFinding.PARAMETERS_REST_NOT_LAST, parameter.name))
    return tuple(parameters), findings


def _parse_dispatch(raw: object) -> tuple[DispatchDeclaration | None, list[EntryFindingDetail]]:
    known_keys = {key.value for key in DispatchKey}
    if not isinstance(raw, Mapping) or not set(raw) <= known_keys:
        return None, [EntryFindingDetail(EntryFinding.DISPATCH_INVALID_VALUE)]
    findings: list[EntryFindingDetail] = []
    raw_agents = raw.get(DispatchKey.AGENT)
    agents: list[AgentName] = []
    if not isinstance(raw_agents, list) or not raw_agents:
        findings.append(EntryFindingDetail(EntryFinding.DISPATCH_AGENT_EMPTY))
    else:
        for item in raw_agents:
            try:
                agents.append(AgentName(item))
            except ValueError:
                findings.append(EntryFindingDetail(EntryFinding.DISPATCH_AGENT_UNKNOWN, str(item)))
    raw_mode = raw.get(DispatchKey.THINKING_MODE)
    mode: ThinkingMode | None = None
    try:
        mode = ThinkingMode(raw_mode)
    except ValueError:
        findings.append(EntryFindingDetail(EntryFinding.DISPATCH_MODE_UNKNOWN, str(raw_mode)))
    else:
        if mode not in DECLARABLE_THINKING_MODES:
            findings.append(EntryFindingDetail(EntryFinding.DISPATCH_MODE_UNKNOWN, str(raw_mode)))
            mode = None
    if findings or mode is None:
        return None, findings
    return DispatchDeclaration(agents=tuple(agents), thinking_mode=mode), findings


def _parse_ending_acts(raw: object) -> tuple[tuple[EndingAct, ...], list[EntryFindingDetail]]:
    if not isinstance(raw, list) or not raw:
        return (), [EntryFindingDetail(EntryFinding.WORKFLOW_ACTS_EMPTY)]
    findings: list[EntryFindingDetail] = []
    acts: list[EndingAct] = []
    seen: set[Act] = set()
    known_keys = {key.value for key in EndingActKey}
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping) or set(item) != known_keys:
            findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_INVALID_VALUE, str(index)))
            continue
        try:
            act = Act(item[EndingActKey.ACT])
        except ValueError:
            findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_ACT_UNKNOWN, str(item[EndingActKey.ACT])))
            continue
        try:
            leads_to = Phase(item[EndingActKey.LEADS_TO])
        except ValueError:
            findings.append(
                EntryFindingDetail(EntryFinding.WORKFLOW_LEADS_TO_UNKNOWN, str(item[EndingActKey.LEADS_TO]))
            )
            continue
        if act in seen:
            findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_ACT_DUPLICATE, act.value))
            continue
        seen.add(act)
        acts.append(EndingAct(act=act, leads_to=leads_to))
    return tuple(acts), findings


def _parse_driven_phases(raw: object) -> tuple[tuple[DrivenPhase, ...], list[EntryFindingDetail]]:
    if not isinstance(raw, list) or not raw:
        return (), [EntryFindingDetail(EntryFinding.WORKFLOW_DRIVES_EMPTY)]
    findings: list[EntryFindingDetail] = []
    phases: list[DrivenPhase] = []
    for item in raw:
        try:
            phase = DrivenPhase(item)
        except ValueError:
            findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_PHASE_UNKNOWN, str(item)))
            continue
        if phase in phases:
            findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_PHASE_DUPLICATE, phase.value))
            continue
        phases.append(phase)
    return tuple(phases), findings


def _admissibility_findings(acts: tuple[EndingAct, ...], held: Phase) -> list[EntryFindingDetail]:
    """The findings for ending acts the machine does not admit in a held phase or whose postcondition differs."""
    findings: list[EntryFindingDetail] = []
    for ending in acts:
        rule = ENDING_ACT_RULES.get(ending.act)
        if rule is None or held not in rule.admissible_in:
            findings.append(
                EntryFindingDetail(EntryFinding.WORKFLOW_ACT_NOT_ADMISSIBLE, f"{ending.act.value}@{held.value}")
            )
            continue
        expected = rule.leads_to if rule.leads_to is not None else held
        if ending.leads_to is not expected:
            findings.append(
                EntryFindingDetail(EntryFinding.WORKFLOW_LEADS_TO_MISMATCH, f"{ending.act.value}@{held.value}")
            )
    return findings


def _parse_child(raw: object) -> str | None:
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def _parse_scopes(
    raw: object, drives: tuple[DrivenPhase, ...]
) -> tuple[tuple[WorkflowScope, ...], list[EntryFindingDetail]]:
    if not isinstance(raw, list):
        return (), [EntryFindingDetail(EntryFinding.WORKFLOW_SCOPE_INVALID)]
    findings: list[EntryFindingDetail] = []
    scopes: list[WorkflowScope] = []
    known_keys = {key.value for key in ScopeKey}
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping) or ScopeKey.PHASE not in item or not set(item) <= known_keys:
            findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_SCOPE_INVALID, str(index)))
            continue
        try:
            phase = DrivenPhase(item[ScopeKey.PHASE])
        except ValueError:
            findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_PHASE_UNKNOWN, str(item[ScopeKey.PHASE])))
            continue
        if phase not in drives:
            findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_SCOPE_PHASE_NOT_DRIVEN, phase.value))
            continue
        if any(scope.phase is phase for scope in scopes):
            findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_SCOPE_DUPLICATE, phase.value))
            continue
        child: str | None = None
        if ScopeKey.CHILD in item:
            child = _parse_child(item[ScopeKey.CHILD])
            if child is None:
                findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_CHILD_MISSING, phase.value))
                continue
        acts, act_findings = _parse_ending_acts(item.get(ScopeKey.ACTS))
        findings.extend(act_findings)
        findings.extend(_admissibility_findings(acts, HELD_PHASE[phase]))
        scopes.append(WorkflowScope(phase=phase, child=child, acts=acts))
    return tuple(scopes), findings


def _parse_workflow(raw: object) -> tuple[WorkflowDeclaration | None, list[EntryFindingDetail]]:
    known_keys = {key.value for key in WorkflowKey}
    if not isinstance(raw, Mapping) or WorkflowKey.DRIVES not in raw or not set(raw) <= known_keys:
        return None, [EntryFindingDetail(EntryFinding.WORKFLOW_INVALID_VALUE)]
    findings: list[EntryFindingDetail] = []
    drives, drive_findings = _parse_driven_phases(raw[WorkflowKey.DRIVES])
    findings.extend(drive_findings)
    scopes: tuple[WorkflowScope, ...] = ()
    if WorkflowKey.SCOPES in raw:
        scopes, scope_findings = _parse_scopes(raw[WorkflowKey.SCOPES], drives)
        findings.extend(scope_findings)
    session: SessionMode | None = None
    if WorkflowKey.SESSION in raw:
        try:
            session = SessionMode(raw[WorkflowKey.SESSION])
        except ValueError:
            findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_SESSION_UNKNOWN, str(raw[WorkflowKey.SESSION])))
    scoped = {scope.phase for scope in scopes}
    unscoped = [phase for phase in drives if phase not in scoped]
    child: str | None = None
    acts: tuple[EndingAct, ...] = ()
    if WorkflowKey.CHILD in raw:
        child = _parse_child(raw[WorkflowKey.CHILD])
        if child is None:
            findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_CHILD_MISSING))
    if WorkflowKey.ACTS in raw:
        acts, act_findings = _parse_ending_acts(raw[WorkflowKey.ACTS])
        findings.extend(act_findings)
    if unscoped:
        if WorkflowKey.CHILD not in raw:
            findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_PHASE_UNCOVERED, unscoped[0].value))
        if WorkflowKey.ACTS not in raw:
            findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_PHASE_UNCOVERED, unscoped[0].value))
        for phase in unscoped:
            findings.extend(_admissibility_findings(acts, HELD_PHASE[phase]))
    if findings:
        return None, findings
    return WorkflowDeclaration(drives=drives, child=child, acts=acts, scopes=scopes, session=session), findings


def parse_entry_declarations(metadata: Mapping[str, object]) -> EntryParse:
    """Read the entry declarations a snippet's metadata carries.

    ``parameters`` and ``dispatch`` declared without a ``role`` are findings; a ``role`` the catalog
    does not name is a finding. A usable entry (``declarations`` set) has a catalog role, well-formed
    parameters and, when declared, well-formed dispatch defaults.
    """
    declared = declares_entry_fields(metadata)
    if not declared:
        return NO_ENTRY_DECLARATIONS
    findings: list[EntryFindingDetail] = []
    raw_role = metadata.get(EntryKey.ROLE)
    role: Role | None = None
    if EntryKey.ROLE in metadata:
        if not isinstance(raw_role, str) or not raw_role.strip():
            findings.append(EntryFindingDetail(EntryFinding.ROLE_INVALID_VALUE))
        else:
            resolved = resolve_role(raw_role)
            if isinstance(resolved, Role):
                role = resolved
            else:
                findings.append(EntryFindingDetail(EntryFinding.ROLE_UNKNOWN, raw_role))
    else:
        if EntryKey.PARAMETERS in metadata:
            findings.append(EntryFindingDetail(EntryFinding.PARAMETERS_WITHOUT_ROLE))
        if EntryKey.DISPATCH in metadata:
            findings.append(EntryFindingDetail(EntryFinding.DISPATCH_WITHOUT_ROLE))
        if EntryKey.WORKFLOW in metadata:
            findings.append(EntryFindingDetail(EntryFinding.WORKFLOW_WITHOUT_ROLE))
    parameters: tuple[ProcedureParameter, ...] = ()
    if EntryKey.PARAMETERS in metadata and EntryKey.ROLE in metadata:
        parameters, parameter_findings = _parse_parameters(metadata[EntryKey.PARAMETERS])
        findings.extend(parameter_findings)
    dispatch: DispatchDeclaration | None = None
    if EntryKey.DISPATCH in metadata and EntryKey.ROLE in metadata:
        dispatch, dispatch_findings = _parse_dispatch(metadata[EntryKey.DISPATCH])
        findings.extend(dispatch_findings)
    workflow: WorkflowDeclaration | None = None
    if EntryKey.WORKFLOW in metadata and EntryKey.ROLE in metadata:
        workflow, workflow_findings = _parse_workflow(metadata[EntryKey.WORKFLOW])
        findings.extend(workflow_findings)
    usable = role is not None and not findings
    declarations = (
        EntryDeclarations(role=role, parameters=parameters, dispatch=dispatch, workflow=workflow)
        if usable and role
        else None
    )
    return EntryParse(declarations=declarations, findings=tuple(findings), declares_entry_fields=True)


class ParameterPayload(TypedDict):
    """One parameter as published and read back."""

    name: str
    required: bool
    default: NotRequired[str]
    rest: NotRequired[bool]


class DispatchPayload(TypedDict):
    """The dispatch defaults as published and read back."""

    agent: list[str]
    thinking_mode: str


class EndingActPayload(TypedDict):
    """One ending act as published and read back."""

    act: str
    leads_to: str


class ScopePayload(TypedDict):
    """One scope as published and read back."""

    phase: str
    child: NotRequired[str]
    acts: list[EndingActPayload]


class WorkflowPayload(TypedDict):
    """The workflow declaration as published and read back."""

    drives: list[str]
    child: NotRequired[str]
    acts: NotRequired[list[EndingActPayload]]
    scopes: NotRequired[list[ScopePayload]]
    session: NotRequired[str]


class EntryPayload(TypedDict):
    """Usable entry declarations in the published-index form that ``parse_entry_declarations`` reads back."""

    role: str
    parameters: NotRequired[list[ParameterPayload]]
    dispatch: NotRequired[DispatchPayload]
    workflow: NotRequired[WorkflowPayload]


def entry_payload(declarations: EntryDeclarations) -> EntryPayload:
    """The published-index form of usable entry declarations."""
    payload = EntryPayload(role=declarations.role.name.value)
    if declarations.parameters:
        payload[EntryKey.PARAMETERS.value] = [_parameter_payload(parameter) for parameter in declarations.parameters]
    if declarations.dispatch is not None:
        payload[EntryKey.DISPATCH.value] = DispatchPayload(
            agent=[agent.value for agent in declarations.dispatch.agents],
            thinking_mode=declarations.dispatch.thinking_mode.value,
        )
    if declarations.workflow is not None:
        payload[EntryKey.WORKFLOW.value] = _workflow_payload(declarations.workflow)
    return payload


def _acts_payload(acts: tuple[EndingAct, ...]) -> list[EndingActPayload]:
    return [EndingActPayload(act=ending.act.value, leads_to=ending.leads_to.value) for ending in acts]


def _scope_payload(scope: WorkflowScope) -> ScopePayload:
    payload = ScopePayload(phase=scope.phase.value, acts=_acts_payload(scope.acts))
    if scope.child is not None:
        payload[ScopeKey.CHILD.value] = scope.child
    return payload


def _workflow_payload(workflow: WorkflowDeclaration) -> WorkflowPayload:
    payload = WorkflowPayload(drives=[phase.value for phase in workflow.drives])
    if workflow.child is not None:
        payload[WorkflowKey.CHILD.value] = workflow.child
    if workflow.acts:
        payload[WorkflowKey.ACTS.value] = _acts_payload(workflow.acts)
    if workflow.scopes:
        payload[WorkflowKey.SCOPES.value] = [_scope_payload(scope) for scope in workflow.scopes]
    if workflow.session is not None:
        payload[WorkflowKey.SESSION.value] = workflow.session.value
    return payload


def _parameter_payload(parameter: ProcedureParameter) -> ParameterPayload:
    payload = ParameterPayload(name=parameter.name, required=parameter.required)
    if parameter.default is not None:
        payload[ParameterKey.DEFAULT.value] = parameter.default
    if parameter.rest:
        payload[ParameterKey.REST.value] = True
    return payload
