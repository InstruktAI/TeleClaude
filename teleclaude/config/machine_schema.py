"""Editor schema projection of the authored computer document, before runtime derivation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from enum import StrEnum
from typing import Final, cast

from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic_core import core_schema

from teleclaude.agent_registry import AgentName
from teleclaude.config import _coerce
from teleclaude.config._agents import _agent_editable_keys
from teleclaude.config._defaults import DEFAULT_CONFIG
from teleclaude.config._machine_build import _DERIVED_ROOT_FIELDS
from teleclaude.config._models import TeleclaudeConfig
from teleclaude.config.schema import CURRENT_SCHEMA_VERSION
from teleclaude.config.tiers import TIER_METADATA_KEY, Tier, effective_tier, in_public_sample
from teleclaude.constants import AGENT_PROTOCOL
from teleclaude.core.models import JsonDict, JsonValue


class _Key(StrEnum):
    DEFS = "$defs"
    REF = "$ref"
    PROPERTIES = "properties"
    REQUIRED = "required"
    TYPE = "type"
    CONST = "const"
    DEFAULT = "default"
    ADDITIONAL = "additionalProperties"
    ANY_OF = "anyOf"
    ITEMS = "items"
    MIN_ITEMS = "minItems"
    DO_NOT_SUGGEST = "doNotSuggest"


class _Field(StrEnum):
    COMPUTER = "computer"
    AGENTS = "agents"
    REMOTE_COMPUTERS = "remote_computers"
    KIND = "kind"
    SCHEMA_VERSION = "schema_version"
    TMUX_BINARY = "tmux_binary"
    NAME = "name"
    PROFILES = "profiles"
    MODEL_CHAINS = "model_chains"
    MODE_CHAINS = "mode_chains"
    DEFAULT = "default"
    ENABLED = "enabled"
    MESSAGE = "message"


_OBJECT = "object"
_ARRAY = "array"
_STRING = "string"
_NULL = "null"
_INTEGER = "integer"
_COMPUTER = "computer"
_REF_PREFIX = "#/$defs/"
_COMPUTER_MODEL = "ComputerConfig"
_AGENT_MODEL = "AgentConfig"
_AGENT_NAME = "AgentName"
_REMOTE_MODEL = "RemoteComputerConfig"
_EVENT_MODEL = "TTSEventConfig"
_VOICE_MODEL = "TTSServiceVoiceConfig"
_DEFAULTED_ENABLED_MODELS = (
    "TTSConfig",
    "TTSServiceConfig",
    "TTSEventConfig",
    "STTConfig",
    "STTServiceConfig",
)
_HOOK_MODEL = "HookOutboxConfig"
_WATERMARKS = frozenset({"session_claim_high_watermark", "session_claim_low_watermark"})
_FUNCTION: Final = "function"
_BOOLEAN = "boolean"
_NUMBER = "number"
_PATTERN = "pattern"
_BOOLEAN_PATTERN = r"^\s*([Tt][Rr][Uu][Ee]|[Yy][Ee][Ss]|1|[Oo][Nn]|[Ff][Aa][Ll][Ss][Ee]|[Nn][Oo]|0|[Oo][Ff][Ff])?\s*$"
_SCALAR_TYPES = (_STRING, _NUMBER, _BOOLEAN, _NULL)
_SUMMARIZER_MODEL = "SummarizerConfig"
_PROVIDER_PRIORITY = "provider_priority"
_SCALAR_SCHEMAS: dict[Callable[..., object], JsonDict] = {
    _coerce._text: {_Key.ANY_OF: [{_Key.TYPE: kind} for kind in _SCALAR_TYPES]},
    _coerce._optional_text: {_Key.ANY_OF: [{_Key.TYPE: kind} for kind in _SCALAR_TYPES]},
    _coerce._truthy_text: {_Key.ANY_OF: [{_Key.TYPE: kind} for kind in _SCALAR_TYPES]},
    _coerce._optional_int_lenient: {_Key.ANY_OF: [{_Key.TYPE: kind} for kind in _SCALAR_TYPES]},
    _coerce._flag: {
        _Key.ANY_OF: [
            {_Key.TYPE: _BOOLEAN},
            {_Key.TYPE: _NULL},
            {_Key.TYPE: _STRING, _PATTERN: _BOOLEAN_PATTERN},
        ]
    },
    _coerce._int_strict: {_Key.ANY_OF: [{_Key.TYPE: _INTEGER}, {_Key.TYPE: _STRING, _PATTERN: r"^\s*[+-]?\d+\s*$"}]},
    _coerce._float_strict: {_Key.ANY_OF: [{_Key.TYPE: _NUMBER}, {_Key.TYPE: _STRING}]},
    _coerce._int_lenient: {_Key.ANY_OF: [{_Key.TYPE: kind} for kind in (_NUMBER, _STRING, _BOOLEAN)]},
}


class _MachineSchemaGenerator(GenerateJsonSchema):
    """Expose the input scalars consumed by machine-only coercion validators."""

    def function_before_schema(self, schema: core_schema.BeforeValidatorFunctionSchema) -> JsonSchemaValue:
        projected = _SCALAR_SCHEMAS.get(schema[_FUNCTION][_FUNCTION])
        return deepcopy(projected) if projected is not None else super().function_before_schema(schema)


def machine_document_schema() -> JsonDict:
    """Project runtime models into file input without changing runtime validation."""
    schema = TeleclaudeConfig.model_json_schema(schema_generator=_MachineSchemaGenerator)
    definitions = cast(dict[str, JsonDict], schema[_Key.DEFS])
    properties = cast(dict[str, JsonDict], schema[_Key.PROPERTIES])
    for derived_field in _DERIVED_ROOT_FIELDS:
        properties.pop(derived_field, None)
    _remove_fields(definitions[_COMPUTER_MODEL], frozenset({_Field.TMUX_BINARY}))
    _remove_fields(definitions[_REMOTE_MODEL], frozenset({_Field.NAME}))
    agent = definitions[_AGENT_MODEL]
    _remove_fields(agent, frozenset(cast(dict[str, JsonDict], agent[_Key.PROPERTIES])) - _agent_editable_keys())
    agent.pop(_Key.REQUIRED, None)
    for model in _DEFAULTED_ENABLED_MODELS:
        _optional_fields(definitions[model], frozenset({_Field.ENABLED}))
    _optional_fields(definitions[_VOICE_MODEL], frozenset({_Field.NAME}))
    _optional_fields(definitions[_HOOK_MODEL], _WATERMARKS)
    summarizer = cast(dict[str, JsonDict], definitions[_SUMMARIZER_MODEL][_Key.PROPERTIES])
    summarizer[_PROVIDER_PRIORITY] = _nullable(summarizer[_PROVIDER_PRIORITY])
    cast(dict[str, JsonDict], definitions[_EVENT_MODEL][_Key.PROPERTIES])[_Field.MESSAGE] = {_Key.TYPE: _STRING}
    properties[_Field.AGENTS] = {
        **_agents_schema(agent),
        TIER_METADATA_KEY: properties[_Field.AGENTS][TIER_METADATA_KEY],
    }
    properties[_Field.REMOTE_COMPUTERS] = _nullable(
        {_Key.TYPE: _OBJECT, _Key.ADDITIONAL: {_Key.REF: _REF_PREFIX + _REMOTE_MODEL}}
    )
    properties[_Field.KIND] = {_Key.CONST: _COMPUTER}
    properties[_Field.SCHEMA_VERSION] = {_Key.TYPE: _INTEGER, _Key.CONST: CURRENT_SCHEMA_VERSION}
    schema[_Key.REQUIRED] = [_Field.COMPUTER, _Field.AGENTS]
    for field, default in DEFAULT_CONFIG.items():
        if field in properties and isinstance(default, Mapping):
            properties[field] = _with_defaults(properties[field], default, definitions)
    return _editor_surface(schema, definitions, Tier.INTERNAL)[0]


def _editor_surface(schema: JsonDict, definitions: dict[str, JsonDict], inherited: Tier) -> tuple[JsonDict, bool]:
    """Keep validation intact while suggesting only explicitly editable fields and their containers."""
    result = deepcopy(schema)
    reference = result.pop(_Key.REF, None)
    if isinstance(reference, str) and reference.startswith(_REF_PREFIX):
        result = {**deepcopy(definitions[reference.removeprefix(_REF_PREFIX)]), **result}
    declared = result.get(TIER_METADATA_KEY)
    tier = effective_tier(Tier(declared) if isinstance(declared, str) else None, inherited)
    visible = in_public_sample(tier)
    properties = result.get(_Key.PROPERTIES)
    if isinstance(properties, dict):
        for name, child in properties.items():
            if isinstance(child, dict):
                properties[name], child_visible = _editor_surface(child, definitions, tier)
                visible = visible or child_visible
    branches = result.get(_Key.ANY_OF)
    if isinstance(branches, list):
        for index, branch in enumerate(branches):
            if isinstance(branch, dict):
                branches[index], child_visible = _editor_surface(branch, definitions, tier)
                visible = visible or child_visible
    for keyword in (_Key.ADDITIONAL, _Key.ITEMS):
        child = result.get(keyword)
        if isinstance(child, dict):
            result[keyword], child_visible = _editor_surface(child, definitions, tier)
            visible = visible or child_visible
    if not visible:
        result[_Key.DO_NOT_SUGGEST] = True
    return result, visible


def _agents_schema(agent: JsonDict) -> JsonDict:
    properties: JsonDict = {_Field.DEFAULT: {_Key.REF: _REF_PREFIX + _AGENT_NAME}}
    for name in AgentName:
        entry = deepcopy(agent)
        fields = cast(dict[str, JsonDict], entry[_Key.PROPERTIES])
        protocol = AGENT_PROTOCOL[name.value]
        fields[_Field.PROFILES] = _nullable(
            {
                _Key.TYPE: _OBJECT,
                _Key.PROPERTIES: {profile: {_Key.TYPE: _STRING} for profile in protocol[_Field.PROFILES.value]},
                _Key.ADDITIONAL: False,
            }
        )
        chain = cast(JsonDict, fields[_Field.MODEL_CHAINS][_Key.ADDITIONAL])
        chain[_Key.MIN_ITEMS] = 1
        fields[_Field.MODEL_CHAINS] = _nullable(
            {
                _Key.TYPE: _OBJECT,
                _Key.PROPERTIES: {
                    mode: deepcopy(chain) for mode in protocol[_Field.MODE_CHAINS.value] if mode != _Field.DEFAULT
                },
                _Key.ADDITIONAL: False,
            }
        )
        properties[name.value] = _nullable(entry)
    return {
        _Key.TYPE: _OBJECT,
        _Key.PROPERTIES: properties,
        _Key.REQUIRED: [_Field.DEFAULT],
        _Key.ADDITIONAL: False,
    }


def _with_defaults(schema: JsonDict, defaults: Mapping[str, object], definitions: dict[str, JsonDict]) -> JsonDict:
    """Apply deep-merge defaults at their actual path, keeping list-entry requirements."""
    result = deepcopy(schema)
    reference = result.pop(_Key.REF, None)
    if isinstance(reference, str) and reference.startswith(_REF_PREFIX):
        result = {**deepcopy(definitions[reference.removeprefix(_REF_PREFIX)]), **result}
    branches = result.get(_Key.ANY_OF)
    if isinstance(branches, list):
        result[_Key.ANY_OF] = [
            _with_defaults(branch, defaults, definitions) if isinstance(branch, dict) else branch for branch in branches
        ]
    _optional_fields(result, frozenset(defaults))
    properties = result.get(_Key.PROPERTIES)
    if isinstance(properties, dict):
        for field, default in defaults.items():
            child = properties.get(field)
            if isinstance(child, dict) and isinstance(default, Mapping):
                properties[field] = _with_defaults(child, default, definitions)
    return result


def _remove_fields(schema: JsonDict, fields: frozenset[str]) -> None:
    properties = cast(dict[str, JsonDict], schema[_Key.PROPERTIES])
    for field in fields:
        properties.pop(field, None)
    _optional_fields(schema, fields)


def _optional_fields(schema: JsonDict, fields: frozenset[str]) -> None:
    required = schema.get(_Key.REQUIRED)
    if isinstance(required, list):
        schema[_Key.REQUIRED] = [field for field in required if field not in fields]


def _nullable(schema: JsonDict) -> JsonDict:
    branches: list[JsonValue] = [schema, {_Key.TYPE: _NULL}]
    return {_Key.ANY_OF: branches}
