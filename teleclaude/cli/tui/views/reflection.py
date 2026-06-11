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


def reflect_schema(
    obj: Any, prefix: str = "", section: str = "General", owning_source: str = "global"
) -> list[ReflectedField]:
    """Inspect a Pydantic model or a dataclass instance and return its ReflectedFields."""
    fields: list[ReflectedField] = []

    # 1. Pydantic BaseModel
    if isinstance(obj, BaseModel):
        for name, field_info in type(obj).model_fields.items():
            extra = field_info.json_schema_extra
            if isinstance(extra, dict) and extra.get("exclude_from_tui"):
                continue

            full_key = f"{prefix}.{name}" if prefix else name
            val = getattr(obj, name)

            # Recurse into nested BaseModels
            if isinstance(val, BaseModel):
                sec_name = name.replace("_", " ").title()
                fields.extend(reflect_schema(val, prefix=full_key, section=sec_name, owning_source=owning_source))
                continue

            ann = field_info.annotation
            ftype, choices = _resolve_type_and_choices(ann)
            desc = field_info.description or ""

            label = name.replace("_", " ").title()

            fields.append(
                ReflectedField(
                    key=full_key,
                    name=label,
                    field_type=ftype,
                    value=val,
                    choices=choices,
                    description=desc,
                    section=section,
                    owning_source=owning_source,
                )
            )

    # 2. Dataclass instance
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        type_hints = get_type_hints(type(obj))
        for f in dataclasses.fields(obj):
            name = f.name
            if f.metadata and f.metadata.get("exclude_from_tui"):
                continue

            full_key = f"{prefix}.{name}" if prefix else name
            val = getattr(obj, name)

            if dataclasses.is_dataclass(val) and not isinstance(val, type):
                sec_name = name.replace("_", " ").title()
                fields.extend(reflect_schema(val, prefix=full_key, section=sec_name, owning_source=owning_source))
                continue

            ann = type_hints.get(name, f.type)
            ftype, choices = _resolve_type_and_choices(ann)
            desc = f.metadata.get("description") if f.metadata else ""

            label = name.replace("_", " ").title()

            fields.append(
                ReflectedField(
                    key=full_key,
                    name=label,
                    field_type=ftype,
                    value=val,
                    choices=choices,
                    description=desc,
                    section=section,
                    owning_source=owning_source,
                )
            )

    # 3. Dict fallback (e.g. nested unstructured dicts)
    elif isinstance(obj, dict):
        for name, val in obj.items():
            full_key = f"{prefix}.{name}" if prefix else name
            if isinstance(val, dict):
                sec_name = name.replace("_", " ").title()
                fields.extend(reflect_schema(val, prefix=full_key, section=sec_name, owning_source=owning_source))
                continue

            ftype = type(val)
            choices = None
            label = name.replace("_", " ").title()

            fields.append(
                ReflectedField(
                    key=full_key,
                    name=label,
                    field_type=ftype,
                    value=val,
                    choices=choices,
                    description=None,
                    section=section,
                    owning_source=owning_source,
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
