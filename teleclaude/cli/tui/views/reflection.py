"""Generic reflection-based configuration schema parser for Pydantic models and dataclasses."""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from enum import Enum
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel


@dataclass
class ReflectedField:
    """Metadata representing a configuration field extracted dynamically."""

    key: str  # e.g., "computer.name" or "stt.enabled"
    name: str  # User-friendly label, e.g. "Name" or "Stt Enabled"
    field_type: Any  # bool, str, list[str], int, float, Enum, Literal
    value: Any  # Current value of the field
    choices: list[str] | None = None  # Allowed choices if Enum or Literal
    description: str | None = None  # Description from field/metadata
    section: str = "General"  # Group name for accordion folding
    env_var: str | None = None  # Backing environment variable when the config value is a ${VAR} reference
    owning_source: str = "global"  # The config source owning this field


def resolve_env_placeholders(fields: list[ReflectedField]) -> None:
    """Resolve ``${VAR}`` field values to their environment value in place.

    A config value like ``${DISCORD_BOT_TOKEN}`` is a reference to a ``.env`` secret,
    not a literal to display or edit. Show the resolved environment value and record
    the variable so the save path writes back to the environment, leaving the
    placeholder in the config untouched.
    """
    for field in fields:
        value = field.value
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            var = value[2:-1]
            field.env_var = var
            field.value = os.environ.get(var, "")


def _unpack_union(t: Any) -> list[Any]:
    if get_origin(t) in (Union, UnionType):
        return list(get_args(t))
    return [t]


def _resolve_type_and_choices(ann: Any) -> tuple[Any, list[str] | None]:
    types = _unpack_union(ann)
    # Check for None type and extract real type
    real_types = [t for t in types if t is not type(None)]
    if not real_types:
        return str, None
    real_type = real_types[0]

    origin = get_origin(real_type)
    if origin is Literal:
        return Literal, [str(arg) for arg in get_args(real_type)]
    if isinstance(real_type, type) and issubclass(real_type, Enum):
        return Enum, [str(choice.value) for choice in real_type]
    if origin is list or real_type is list:
        args = get_args(real_type)
        if args and args[0] is str:
            return list[str], None
        return list, None

    return real_type, None


def _struct_type_from_annotation(ann: Any) -> Any | None:
    """Return the nested BaseModel/dataclass type within an annotation, or None."""
    for candidate in _unpack_union(ann):
        if candidate is type(None):
            continue
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate
        if isinstance(candidate, type) and dataclasses.is_dataclass(candidate):
            return candidate
    return None


def _is_struct_value(value: Any) -> bool:
    """Whether a value is a nested structure the walker descends into."""
    return isinstance(value, (BaseModel, dict)) or (dataclasses.is_dataclass(value) and not isinstance(value, type))


def _reflect_field(
    full_key: str,
    label: str,
    section: str,
    owning_source: str,
    annotation: Any,
    value: Any,
    description: str | None,
) -> list[ReflectedField]:
    """Recurse into a nested struct/dict/list, or emit a single leaf field.

    Recursion is driven by the value when one is present (a model, dataclass,
    dict, or list of those), and by the declared type when the value is an unset
    ``Optional`` nested struct — so a structure renders to its leaves regardless of
    whether it is currently populated. A list of scalars stays a single editable
    leaf; a list of structs expands to one indexed subtree per element.
    """
    if _is_struct_value(value):
        return reflect_schema(value, prefix=full_key, section=label, owning_source=owning_source)

    if isinstance(value, list) and any(_is_struct_value(item) for item in value):
        items: list[ReflectedField] = []
        for index, item in enumerate(value):
            items.extend(
                _reflect_field(f"{full_key}.{index}", f"{label} {index}", label, owning_source, None, item, None)
            )
        return items

    if value is None and annotation is not None:
        nested = _struct_type_from_annotation(annotation)
        if nested is not None:
            return _reflect_type(nested, full_key, label, owning_source)

    if annotation is not None:
        ftype, choices = _resolve_type_and_choices(annotation)
    else:
        ftype, choices = type(value), None

    return [
        ReflectedField(
            key=full_key,
            name=label,
            field_type=ftype,
            value=value,
            choices=choices,
            description=description,
            section=section,
            owning_source=owning_source,
        )
    ]


def _reflect_type(struct_type: Any, prefix: str, section: str, owning_source: str) -> list[ReflectedField]:
    """Reflect an unset nested struct *type* into value-None leaf fields."""
    fields: list[ReflectedField] = []
    if isinstance(struct_type, type) and issubclass(struct_type, BaseModel):
        for name, field_info in struct_type.model_fields.items():
            extra = field_info.json_schema_extra
            if isinstance(extra, dict) and extra.get("exclude_from_tui"):
                continue
            fields.extend(
                _reflect_field(
                    f"{prefix}.{name}" if prefix else name,
                    name.replace("_", " ").title(),
                    section,
                    owning_source,
                    field_info.annotation,
                    None,
                    field_info.description or "",
                )
            )
    elif isinstance(struct_type, type) and dataclasses.is_dataclass(struct_type):
        type_hints = get_type_hints(struct_type)
        for f in dataclasses.fields(struct_type):
            if f.metadata and f.metadata.get("exclude_from_tui"):
                continue
            fields.extend(
                _reflect_field(
                    f"{prefix}.{f.name}" if prefix else f.name,
                    f.name.replace("_", " ").title(),
                    section,
                    owning_source,
                    type_hints.get(f.name, f.type),
                    None,
                    f.metadata.get("description") if f.metadata else None,
                )
            )
    return fields


def reflect_schema(
    obj: Any, prefix: str = "", section: str = "General", owning_source: str = "global"
) -> list[ReflectedField]:
    """Inspect a Pydantic model, dataclass instance, or dict and return its ReflectedFields."""
    fields: list[ReflectedField] = []

    if isinstance(obj, BaseModel):
        for name, field_info in type(obj).model_fields.items():
            extra = field_info.json_schema_extra
            if isinstance(extra, dict) and extra.get("exclude_from_tui"):
                continue
            fields.extend(
                _reflect_field(
                    f"{prefix}.{name}" if prefix else name,
                    name.replace("_", " ").title(),
                    section,
                    owning_source,
                    field_info.annotation,
                    getattr(obj, name),
                    field_info.description or "",
                )
            )

    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        type_hints = get_type_hints(type(obj))
        for f in dataclasses.fields(obj):
            if f.metadata and f.metadata.get("exclude_from_tui"):
                continue
            fields.extend(
                _reflect_field(
                    f"{prefix}.{f.name}" if prefix else f.name,
                    f.name.replace("_", " ").title(),
                    section,
                    owning_source,
                    type_hints.get(f.name, f.type),
                    getattr(obj, f.name),
                    f.metadata.get("description") if f.metadata else None,
                )
            )

    elif isinstance(obj, dict):
        for name, val in obj.items():
            fields.extend(
                _reflect_field(
                    f"{prefix}.{name}" if prefix else str(name),
                    str(name).replace("_", " ").title(),
                    section,
                    owning_source,
                    None,
                    val,
                    None,
                )
            )

    return fields


def deserialize_value(value_str: str | bool | list[str], ftype: Any, choices: list[str] | None = None) -> Any:
    """Deserialize TUI value back into correct Python type matching field_type."""
    if isinstance(value_str, bool):
        return value_str

    if isinstance(value_str, list):
        return value_str

    if ftype is bool:
        return value_str.lower() in ("true", "yes", "1", "t", "y")
    if ftype is int:
        try:
            return int(value_str)
        except ValueError:
            raise ValueError(f"'{value_str}' is not a valid integer") from None
    if ftype is float:
        try:
            return float(value_str)
        except ValueError:
            raise ValueError(f"'{value_str}' is not a valid number") from None
    if ftype == list[str] or ftype is list or get_origin(ftype) is list:
        return [item.strip() for item in value_str.split(",") if item.strip()]
    if ftype is Literal or ftype is Enum:
        if choices and value_str not in choices:
            raise ValueError(f"'{value_str}' is not one of: {', '.join(choices)}")
        return value_str

    return value_str
