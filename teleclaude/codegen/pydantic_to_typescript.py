"""Generate TypeScript types from Pydantic API models."""

from __future__ import annotations

import inspect
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import NoneType, UnionType
from typing import Any, Literal, TypeAliasType, Union, cast, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from teleclaude import api_models

_HEADER_LINES: tuple[str, ...] = (
    "/**",
    " * Auto-generated from teleclaude.api_models.",
    " * Do not edit by hand.",
    " */",
)
_DEFAULT_OUTPUT_PATH = Path("frontend/lib/api/generated-types.ts")
_MODEL_NAME_OVERRIDES: dict[str, str] = {
    "OperationStatusDTO": "OperationStatus",
    "SessionLifecycleStatusEventDTO": "SessionStatusEvent",
    "SessionMessagesDTO": "SessionMessagesResponse",
}
_RESOURCE_DTO_NAMES: frozenset[str] = frozenset(
    {
        "AgentAvailabilityDTO",
        "ComputerDTO",
        "JobDTO",
        "MessageDTO",
        "PersonDTO",
        "ProjectDTO",
        "ProjectWithTodosDTO",
        "SessionDTO",
        "TodoDTO",
    }
)
_LITERAL_ALIAS_VALUES: dict[str, tuple[str, ...]] = {
    "AgentName": ("claude", "gemini", "codex"),
    "ThinkingMode": ("fast", "med", "slow"),
    "HumanRole": ("admin", "member", "contributor", "newcomer"),
    "LaunchKind": ("empty", "agent", "agent_then_message", "agent_resume"),
    "AgentStatus": ("available", "unavailable", "degraded"),
    "ErrorSeverity": ("warning", "error", "critical"),
    "MessageRole": ("user", "assistant", "system"),
    "MessageType": ("text", "compaction", "tool_use", "tool_result", "thinking"),
    "RefreshEventType": (
        "computer_updated",
        "project_updated",
        "projects_updated",
        "todos_updated",
        "todo_created",
        "todo_updated",
        "todo_removed",
    ),
}


def _discover_pep695_literal_aliases() -> dict[str, tuple[str, ...]]:
    """Auto-discover ``type X = Literal[...]`` aliases declared in api_models.

    PEP 695 type aliases are first-class Python objects (``TypeAliasType``)
    distinct from the ``typing.Literal`` they wrap. ``get_origin`` on the alias
    itself returns ``None``, so the codegen has to unwrap ``__value__`` to see
    the underlying ``Literal``. Auto-discovery here avoids hand-maintaining the
    alias registry every time a new ``type X = Literal[...]`` is added to
    api_models.
    """
    discovered: dict[str, tuple[str, ...]] = {}
    for name, candidate in inspect.getmembers(api_models):
        if not isinstance(candidate, TypeAliasType):
            continue
        underlying = candidate.__value__
        if get_origin(underlying) is Literal:
            discovered[name] = tuple(str(v) for v in get_args(underlying))
    return discovered


_LITERAL_ALIAS_VALUES.update(_discover_pep695_literal_aliases())
_LITERAL_ALIAS_LOOKUP: dict[frozenset[str], str] = {
    frozenset(values): alias_name for alias_name, values in _LITERAL_ALIAS_VALUES.items()
}
_AGENT_ACTIVITY_EVENT_MEMBERS: tuple[str, ...] = (
    "UserPromptSubmitActivityEvent",
    "ToolUseActivityEvent",
    "AgentStopActivityEvent",
)
# Optionality overrides preserve the shape the frontend already consumes when
# the Python default alone would produce a stricter or looser signal than the
# hand-maintained contract did. Each entry documents a boundary the frontend
# relies on beyond what the Pydantic default communicates.
_OPTIONAL_FIELD_OVERRIDES: frozenset[tuple[str, str]] = frozenset(
    {
        # ProjectWithTodosDTO.has_todo defaults to False, but frontend consumers
        # treat the field as optional because older payloads omit it entirely.
        ("ProjectWithTodosDTO", "has_todo"),
        # SessionDTO.visibility has the literal default "private"; the frontend
        # treats it as optional to tolerate payloads from pre-visibility sessions.
        ("SessionDTO", "visibility"),
        # TodoDTO.after uses a default factory (empty list); the frontend import
        # surface has always declared it optional to avoid forcing consumers to
        # pass an empty array when assembling a TodoInfo in tests.
        ("TodoDTO", "after"),
        # TodoDTO.version_total defaults to zero; older daemon/cache payloads and
        # frontend fixtures may omit it while callers normalize absence to zero.
        ("TodoDTO", "version_total"),
    }
)
# Required overrides force a nullable-but-always-present shape even though the
# Python field has a None default. The backend emits these fields on every
# response, so the frontend contract is "present, possibly null".
_REQUIRED_FIELD_OVERRIDES: frozenset[tuple[str, str]] = frozenset(
    {
        # JobDTO.last_run and JobDTO.schedule are always serialized by the job
        # listing endpoint; the frontend relies on the key being present.
        ("JobDTO", "last_run"),
        ("JobDTO", "schedule"),
    }
)


def _discover_models() -> list[type[BaseModel]]:
    """Return API model classes in a deterministic order."""
    models: list[type[BaseModel]] = []
    for _, candidate in inspect.getmembers(api_models, inspect.isclass):
        if not issubclass(candidate, BaseModel):
            continue
        if candidate.__module__ != api_models.__name__:
            continue
        models.append(candidate)
    return sorted(models, key=lambda model_cls: _interface_sort_key(model_cls.__name__))


def _typescript_name(python_name: str) -> str:
    """Map a Python API model name to the frontend TypeScript name."""
    if python_name.endswith("Request"):
        return python_name
    override = _MODEL_NAME_OVERRIDES.get(python_name)
    if override is not None:
        return override
    if python_name in _RESOURCE_DTO_NAMES:
        return f"{python_name.removesuffix('DTO')}Info"
    if python_name.endswith("DTO"):
        return python_name.removesuffix("DTO")
    return python_name


def _interface_sort_key(python_name: str) -> tuple[int, str]:
    """Keep request and patch shapes ahead of response/event interfaces."""
    type_name = _typescript_name(python_name)
    is_input_shape = python_name.endswith("Request") or python_name.endswith("PatchDTO")
    return (0 if is_input_shape else 1, type_name)


def _is_optional_property(model_name: str, field_name: str, field: FieldInfo) -> bool:
    """Return whether the generated property should use the optional marker."""
    field_key = (model_name, field_name)
    if field_key in _REQUIRED_FIELD_OVERRIDES:
        return False
    if field_key in _OPTIONAL_FIELD_OVERRIDES:
        return True
    if field.default is None:
        return True
    return (model_name.endswith("Request") or model_name.endswith("PatchDTO")) and not field.is_required()


def _render_literal_value(value: object) -> str:
    """Render a Python literal as a TypeScript literal token."""
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


def _select_literal_alias(model_name: str, field_name: str, values: tuple[object, ...]) -> str | None:
    """Return a named literal alias for a known value set."""
    if model_name == "CreateSessionRequest" and field_name == "thinking_mode":
        return None
    string_values = tuple(value for value in values if isinstance(value, str))
    if len(string_values) != len(values):
        return None
    return _LITERAL_ALIAS_LOOKUP.get(frozenset(string_values))


def _dedupe_types(type_names: list[str]) -> list[str]:
    """Preserve order while removing duplicate TypeScript members."""
    seen: set[str] = set()
    result: list[str] = []
    for type_name in type_names:
        if type_name in seen:
            continue
        seen.add(type_name)
        result.append(type_name)
    return result


def _map_union_annotation(
    annotation: object,
    *,
    model_name: str,
    field_name: str,
    used_literal_aliases: set[str],
) -> str:
    """Map a Python union annotation to a TypeScript union."""
    type_names: list[str] = []
    for member in get_args(annotation):
        if member is NoneType:
            type_names.append("null")
            continue
        type_names.append(
            _map_annotation(
                member,
                model_name=model_name,
                field_name=field_name,
                used_literal_aliases=used_literal_aliases,
            )
        )
    return " | ".join(_dedupe_types(type_names))


def _map_list_annotation(
    annotation: object,
    *,
    model_name: str,
    field_name: str,
    used_literal_aliases: set[str],
) -> str:
    """Map a Python list annotation to a TypeScript array."""
    item_annotation = get_args(annotation)[0]
    item_type = _map_annotation(
        item_annotation,
        model_name=model_name,
        field_name=field_name,
        used_literal_aliases=used_literal_aliases,
    )
    wrapped_item_type = f"({item_type})" if " | " in item_type else item_type
    return f"{wrapped_item_type}[]"


def _map_dict_annotation(
    annotation: object,
    *,
    model_name: str,
    field_name: str,
    used_literal_aliases: set[str],
) -> str:
    """Map a Python dict annotation to a TypeScript Record."""
    key_annotation, value_annotation = get_args(annotation)
    key_type = _map_annotation(
        key_annotation,
        model_name=model_name,
        field_name=field_name,
        used_literal_aliases=used_literal_aliases,
    )
    value_type = _map_annotation(
        value_annotation,
        model_name=model_name,
        field_name=field_name,
        used_literal_aliases=used_literal_aliases,
    )
    return f"Record<{key_type}, {value_type}>"


def _map_literal_annotation(
    annotation: object,
    *,
    model_name: str,
    field_name: str,
    used_literal_aliases: set[str],
) -> str:
    """Map a Python Literal annotation to a TypeScript literal union."""
    values = cast(tuple[object, ...], get_args(annotation))
    alias_name = _select_literal_alias(model_name, field_name, values)
    if alias_name is not None:
        used_literal_aliases.add(alias_name)
        return alias_name
    return " | ".join(_render_literal_value(value) for value in values)


def _map_scalar_annotation(annotation: object) -> str | None:
    """Map primitive Python types to TypeScript primitives."""
    if annotation is str:
        return "string"
    if annotation is int or annotation is float:
        return "number"
    if annotation is bool:
        return "boolean"
    if annotation is object or annotation is Any:
        return "unknown"
    if annotation is NoneType:
        return "null"
    return None


def _map_model_annotation(annotation: object) -> str | None:
    """Map nested Pydantic model references to named TypeScript references."""
    if not inspect.isclass(annotation):
        return None
    candidate = cast(type[object], annotation)
    if not issubclass(candidate, BaseModel):
        return None
    return _typescript_name(candidate.__name__)


def _map_annotation(
    annotation: object,
    *,
    model_name: str,
    field_name: str,
    used_literal_aliases: set[str],
) -> str:
    """Map a Python type annotation to a TypeScript type string."""
    if isinstance(annotation, TypeAliasType):
        return _map_annotation(
            annotation.__value__,
            model_name=model_name,
            field_name=field_name,
            used_literal_aliases=used_literal_aliases,
        )
    origin = get_origin(annotation)
    mapped_type: str | None = None
    if origin in {Union, UnionType}:
        mapped_type = _map_union_annotation(
            annotation,
            model_name=model_name,
            field_name=field_name,
            used_literal_aliases=used_literal_aliases,
        )
    elif origin is list:
        mapped_type = _map_list_annotation(
            model_name=model_name,
            field_name=field_name,
            annotation=annotation,
            used_literal_aliases=used_literal_aliases,
        )
    elif origin is dict:
        mapped_type = _map_dict_annotation(
            model_name=model_name,
            field_name=field_name,
            annotation=annotation,
            used_literal_aliases=used_literal_aliases,
        )
    elif origin is Literal:
        mapped_type = _map_literal_annotation(
            model_name=model_name,
            field_name=field_name,
            annotation=annotation,
            used_literal_aliases=used_literal_aliases,
        )
    else:
        mapped_type = _map_scalar_annotation(annotation)
        if mapped_type is None:
            mapped_type = _map_model_annotation(annotation)
    if mapped_type is None:
        raise ValueError(f"No TypeScript mapping for annotation {annotation!r} on {model_name}.{field_name}")
    return mapped_type


def _render_field(
    model_name: str,
    field_name: str,
    field: FieldInfo,
    used_literal_aliases: set[str],
) -> str:
    """Render a single TypeScript property declaration."""
    optional_marker = "?" if _is_optional_property(model_name, field_name, field) else ""
    type_name = _map_annotation(
        field.annotation,
        model_name=model_name,
        field_name=field_name,
        used_literal_aliases=used_literal_aliases,
    )
    return f"  {field_name}{optional_marker}: {type_name};"


def _render_literal_alias(alias_name: str) -> str:
    """Render a named string literal union alias."""
    values = _LITERAL_ALIAS_VALUES[alias_name]
    members = " | ".join(_render_literal_value(value) for value in values)
    return f"export type {alias_name} = {members};"


def _render_compatibility_alias(model_cls: type[BaseModel]) -> str | None:
    """Render a non-DTO compatibility alias when an override hides the base concept."""
    python_name = model_cls.__name__
    if not python_name.endswith("DTO"):
        return None
    base_name = python_name.removesuffix("DTO")
    type_name = _typescript_name(python_name)
    if base_name == type_name or base_name in type_name:
        return None
    return f"export type {base_name} = {type_name};"


def _direct_api_model_parents(model_cls: type[BaseModel]) -> list[type[BaseModel]]:
    """Return direct BaseModel parents that are generated from api_models.py."""
    parents: list[type[BaseModel]] = []
    for base_cls in model_cls.__bases__:
        if base_cls in {BaseModel, object}:
            continue
        if not issubclass(base_cls, BaseModel):
            continue
        if base_cls.__module__ != api_models.__name__:
            continue
        parents.append(base_cls)
    return parents


def _field_overrides_parent(field: FieldInfo, parent_field: FieldInfo) -> bool:
    """Return whether a child field differs from the inherited parent field."""
    return (
        field.annotation != parent_field.annotation
        or field.default != parent_field.default
        or field.default_factory != parent_field.default_factory
    )


def _rendered_fields_for_model(model_cls: type[BaseModel]) -> list[tuple[str, FieldInfo]]:
    """Return the fields that belong in the rendered interface body."""
    parents = _direct_api_model_parents(model_cls)
    if len(parents) != 1:
        return list(model_cls.model_fields.items())

    parent_fields = parents[0].model_fields
    rendered_fields: list[tuple[str, FieldInfo]] = []
    for field_name, field in model_cls.model_fields.items():
        parent_field = parent_fields.get(field_name)
        if parent_field is None or _field_overrides_parent(field, parent_field):
            rendered_fields.append((field_name, field))
    return rendered_fields


def _extends_clause(model_cls: type[BaseModel]) -> str:
    """Return a TypeScript extends clause for single-parent API model inheritance."""
    parents = _direct_api_model_parents(model_cls)
    if len(parents) != 1:
        return ""
    return f" extends {_typescript_name(parents[0].__name__)}"


def _render_agent_activity_event_alias() -> str:
    """Render the generated AgentActivityEvent discriminated union."""
    members = " | ".join(_AGENT_ACTIVITY_EVENT_MEMBERS)
    return f"export type AgentActivityEvent = {members};"


def _render_model(model_cls: type[BaseModel], used_literal_aliases: set[str]) -> str:
    """Render a model as a TypeScript interface."""
    lines = [f"export interface {_typescript_name(model_cls.__name__)}{_extends_clause(model_cls)} {{"]
    for field_name, field in _rendered_fields_for_model(model_cls):
        lines.append(_render_field(model_cls.__name__, field_name, field, used_literal_aliases))
    lines.append("}")
    return "\n".join(lines)


def generate() -> str:
    """Return TypeScript declarations for API models."""
    models = _discover_models()
    used_literal_aliases: set[str] = set()
    rendered_models = [_render_model(model_cls, used_literal_aliases) for model_cls in models]
    rendered_aliases: dict[str, str] = {
        alias_name: _render_literal_alias(alias_name) for alias_name in sorted(used_literal_aliases)
    }
    rendered_aliases["AgentActivityEvent"] = _render_agent_activity_event_alias()
    for model_cls in models:
        compatibility_alias = _render_compatibility_alias(model_cls)
        if compatibility_alias is None:
            continue
        alias_name = compatibility_alias.removeprefix("export type ").split(" = ", maxsplit=1)[0]
        rendered_aliases[alias_name] = compatibility_alias

    sections = ["\n".join(_HEADER_LINES)]
    alias_block = "\n".join(rendered_aliases[alias_name] for alias_name in sorted(rendered_aliases)).strip()
    if alias_block:
        sections.append(alias_block)
    sections.append("\n\n".join(rendered_models))
    return "\n\n".join(sections).rstrip() + "\n"


def write_generated_file(path: Path) -> None:
    """Write the generated TypeScript declarations to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate(), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Write generated types to the requested output path."""
    args = list(argv) if argv is not None else sys.argv[1:]
    output_path = Path(args[0]) if args else _DEFAULT_OUTPUT_PATH
    write_generated_file(output_path)
    print(f"TypeScript written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
