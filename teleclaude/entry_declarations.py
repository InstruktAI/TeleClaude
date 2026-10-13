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
from teleclaude.helpers.agent_types import ThinkingMode


class EntryKey(StrEnum):
    """The frontmatter and published-index keys carrying a procedure's entry declarations."""

    ROLE = "role"
    PARAMETERS = "parameters"
    DISPATCH = "dispatch"


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
class EntryDeclarations:
    """What a procedure declares as a launch root. ``dispatch`` is ``None`` when it declares none."""

    role: Role
    parameters: tuple[ProcedureParameter, ...]
    dispatch: DispatchDeclaration | None


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
    parameters: tuple[ProcedureParameter, ...] = ()
    if EntryKey.PARAMETERS in metadata and EntryKey.ROLE in metadata:
        parameters, parameter_findings = _parse_parameters(metadata[EntryKey.PARAMETERS])
        findings.extend(parameter_findings)
    dispatch: DispatchDeclaration | None = None
    if EntryKey.DISPATCH in metadata and EntryKey.ROLE in metadata:
        dispatch, dispatch_findings = _parse_dispatch(metadata[EntryKey.DISPATCH])
        findings.extend(dispatch_findings)
    usable = role is not None and not findings
    declarations = EntryDeclarations(role=role, parameters=parameters, dispatch=dispatch) if usable and role else None
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


class EntryPayload(TypedDict):
    """Usable entry declarations in the published-index form that ``parse_entry_declarations`` reads back."""

    role: str
    parameters: NotRequired[list[ParameterPayload]]
    dispatch: NotRequired[DispatchPayload]


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
    return payload


def _parameter_payload(parameter: ProcedureParameter) -> ParameterPayload:
    payload = ParameterPayload(name=parameter.name, required=parameter.required)
    if parameter.default is not None:
        payload[ParameterKey.DEFAULT.value] = parameter.default
    if parameter.rest:
        payload[ParameterKey.REST.value] = True
    return payload
