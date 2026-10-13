"""Config surface markdown export for release inspector prompts.

Generates a structured markdown document from Pydantic config models,
suitable for injection into AI inspector prompts at pipeline runtime.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Final

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema

from teleclaude.config._environment import WHOLE_REFERENCE_SCHEMA_PATTERN
from teleclaude.config.machine_schema import machine_document_schema
from teleclaude.config.schema import TIER_DOCUMENT_MODELS, ConfigKind, GlobalConfig, PersonConfig, ProjectConfig
from teleclaude.core.models import JsonDict, JsonValue

_DIALECT_KEY: Final = "$schema"

_MODELS: list[tuple[str, type[BaseModel]]] = [
    ("Global Config", GlobalConfig),
    ("Project Config", ProjectConfig),
    ("Person Config", PersonConfig),
]


class _Keyword(StrEnum):
    """JSON Schema keywords the reference widening reads or writes."""

    TYPE = "type"
    ENUM = "enum"
    CONST = "const"


class _StringConstraint(StrEnum):
    """JSON Schema keywords that constrain a string beyond its type."""

    PATTERN = "pattern"
    FORMAT = "format"
    MIN_LENGTH = "minLength"
    MAX_LENGTH = "maxLength"


class _ValueType(StrEnum):
    """JSON Schema value types a configuration leaf declares."""

    STRING = "string"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"


class _Annotation(StrEnum):
    """JSON Schema annotation keywords; they describe a field and stay on it when its type is widened."""

    TITLE = "title"
    DESCRIPTION = "description"
    DEFAULT = "default"
    EXAMPLES = "examples"
    DEPRECATED = "deprecated"
    READ_ONLY = "readOnly"
    WRITE_ONLY = "writeOnly"
    DO_NOT_SUGGEST = "doNotSuggest"


class _SubschemaMap(StrEnum):
    """Keywords whose value maps names to subschemas."""

    DEFS = "$defs"
    PROPERTIES = "properties"
    PATTERN_PROPERTIES = "patternProperties"


class _SubschemaList(StrEnum):
    """Keywords whose value is a list of subschemas."""

    ANY_OF = "anyOf"
    ONE_OF = "oneOf"
    ALL_OF = "allOf"
    PREFIX_ITEMS = "prefixItems"


class _Subschema(StrEnum):
    """Keywords whose value is one subschema."""

    ITEMS = "items"
    ADDITIONAL_PROPERTIES = "additionalProperties"
    NOT = "not"
    IF = "if"
    THEN = "then"
    ELSE = "else"


class _PreExpansionField(StrEnum):
    """Tier document fields read from the raw document before its references are expanded."""

    KIND = "kind"
    SCHEMA_VERSION = "schema_version"


_REFERENCE_SCHEMA: Final[JsonDict] = {
    _Keyword.TYPE: _ValueType.STRING,
    _StringConstraint.PATTERN: WHOLE_REFERENCE_SCHEMA_PATTERN,
}
_NON_STRING_LEAF_TYPES: Final = frozenset({_ValueType.BOOLEAN, _ValueType.INTEGER, _ValueType.NUMBER})
_ANNOTATIONS: Final = frozenset(_Annotation)
_STRING_CONSTRAINTS: Final = frozenset(_StringConstraint)
_SUBSCHEMA_MAPS: Final = frozenset(_SubschemaMap)
_SUBSCHEMA_LISTS: Final = frozenset(_SubschemaList)
_SUBSCHEMAS: Final = frozenset(_Subschema)


def export_tier_schemas() -> dict[ConfigKind, JsonDict]:
    """Return one JSON Schema document for each declared configuration tier, stating its dialect.

    Each schema describes the authored document rather than the resolved one: a constrained scalar
    field also accepts a value that is one whole environment reference.
    """
    return {
        kind: {_DIALECT_KEY: GenerateJsonSchema.schema_dialect, **_accept_references(model.model_json_schema())}
        for kind, model in TIER_DOCUMENT_MODELS.items()
    }


def export_computer_schema() -> JsonDict:
    """Return the computer's authored-input schema with environment references accepted."""
    return {_DIALECT_KEY: GenerateJsonSchema.schema_dialect, **_accept_references(machine_document_schema())}


def _accept_references(schema: JsonDict) -> JsonDict:
    """Widen every constrained leaf to also accept a whole reference, except the pre-expansion fields."""
    widened = _widen_subschemas(schema)
    original_properties = schema.get(_SubschemaMap.PROPERTIES)
    widened_properties = widened.get(_SubschemaMap.PROPERTIES)
    if isinstance(original_properties, dict) and isinstance(widened_properties, dict):
        for field in _PreExpansionField:
            if field in original_properties:
                widened_properties[field] = original_properties[field]
    return widened


def _widen(node: JsonValue) -> JsonValue:
    """Return a subschema that also accepts a whole reference wherever its leaf constraint would refuse one."""
    if not isinstance(node, dict):
        return node
    if not _refuses_reference(node):
        return _widen_subschemas(node)
    annotations = {key: value for key, value in node.items() if key in _ANNOTATIONS}
    constraint = {key: value for key, value in node.items() if key not in _ANNOTATIONS}
    return {**annotations, _SubschemaList.ANY_OF: [constraint, dict(_REFERENCE_SCHEMA)]}


def _widen_subschemas(node: JsonDict) -> JsonDict:
    """Widen the subschemas a schema node holds, leaving its other keywords untouched."""
    widened: JsonDict = {}
    for key, value in node.items():
        if key in _SUBSCHEMA_MAPS and isinstance(value, dict):
            widened[key] = {name: _widen(child) for name, child in value.items()}
        elif key in _SUBSCHEMA_LISTS and isinstance(value, list):
            widened[key] = [_widen(child) for child in value]
        elif key in _SUBSCHEMAS:
            widened[key] = _widen(value)
        else:
            widened[key] = value
    return widened


def _refuses_reference(node: JsonDict) -> bool:
    """Whether a leaf subschema refuses a string of the form ``${NAME}``."""
    if _Keyword.ENUM in node or _Keyword.CONST in node:
        return True
    declared = node.get(_Keyword.TYPE)
    if declared in _NON_STRING_LEAF_TYPES:
        return True
    return declared == _ValueType.STRING and any(key in _STRING_CONSTRAINTS for key in node)


def export_config_markdown() -> str:
    """Return a markdown document describing the TeleClaude config surface.

    Pure function — no I/O, no daemon. Safe for CI usage.
    """
    sections: list[str] = ["# TeleClaude Configuration Surface\n"]

    for label, model in _MODELS:
        schema = model.model_json_schema()
        sections.append(f"## {label}\n")
        sections.append(f"Model: `{model.__name__}`\n")

        props = schema.get("properties", {})
        if props:
            sections.append("| Field | Type | Description |")
            sections.append("|-------|------|-------------|")
            for field_name, field_info in sorted(props.items()):
                field_type = _resolve_type(field_info)
                desc = field_info.get("description", field_info.get("title", ""))
                sections.append(f"| `{field_name}` | {field_type} | {desc} |")
            sections.append("")

        # Include $defs for nested models
        defs = schema.get("$defs", {})
        if defs:
            sections.append(f"### {label} — Nested Types\n")
            for def_name, def_schema in sorted(defs.items()):
                sections.append(f"#### {def_name}\n")
                def_props = def_schema.get("properties", {})
                if def_props:
                    sections.append("| Field | Type | Description |")
                    sections.append("|-------|------|-------------|")
                    for field_name, field_info in sorted(def_props.items()):
                        field_type = _resolve_type(field_info)
                        desc = field_info.get("description", field_info.get("title", ""))
                        sections.append(f"| `{field_name}` | {field_type} | {desc} |")
                    sections.append("")

    # Append raw JSON schema as reference
    sections.append("## Raw JSON Schema\n")
    sections.append("```json")
    raw_schema = {label: model.model_json_schema() for label, model in _MODELS}
    sections.append(json.dumps(raw_schema, indent=2))
    sections.append("```\n")

    return "\n".join(sections)


def _resolve_type(
    field_info: dict[str, object],  # guard: loose-dict - JSON schema field info is untyped at runtime
) -> str:
    """Extract a human-readable type string from a JSON Schema field."""
    if "type" in field_info:
        return str(field_info["type"])
    if "anyOf" in field_info:
        any_of = field_info["anyOf"]
        types = [_resolve_type(t) for t in any_of] if isinstance(any_of, list) else []
        return " | ".join(types)
    if "allOf" in field_info:
        all_of = field_info["allOf"]
        types = [_resolve_type(t) for t in all_of] if isinstance(all_of, list) else []
        return " & ".join(types)
    if "$ref" in field_info:
        ref = str(field_info["$ref"])
        return ref.rsplit("/", 1)[-1]
    if "const" in field_info:
        return repr(field_info["const"])
    if "enum" in field_info:
        enum_vals = field_info["enum"]
        return " | ".join(repr(v) for v in enum_vals) if isinstance(enum_vals, list) else "any"
    return "any"
