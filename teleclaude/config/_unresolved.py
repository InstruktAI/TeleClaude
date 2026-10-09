"""A configuration value whose environment reference has no value on this computer is absent.

Expansion keeps such a whole-value reference as its ``${NAME}`` placeholder; the cleaner here
removes every placeholder leaf, guided by the destination model, so the field takes its declared
default or stays unset. Machine and tier documents share this one cleaner; a caller supplies
overrides only for fields whose shape the model annotations cannot describe.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import UnionType
from typing import Final, Union, get_args, get_origin

from teleclaude.closed_model import ClosedModel
from teleclaude.config._environment import whole_reference_name

DROP: Final = object()
"""Returned by a cleaner for a value that is absent and must be left out of its container."""

type FieldCleaner = Callable[[object], object]
type FieldOverrides = Mapping[tuple[type[ClosedModel], str], FieldCleaner]

NO_OVERRIDES: Final[FieldOverrides] = {}


def is_unresolved(value: object) -> bool:
    """Whether a value is a whole-value reference that resolved to nothing on this computer."""
    return isinstance(value, str) and whole_reference_name(value) is not None


def drop_unresolved_fields(value: object, model_type: type[ClosedModel], overrides: FieldOverrides) -> object:
    """Remove unresolved leaves from a mapping destined for ``model_type``."""
    if not isinstance(value, Mapping):
        return value
    cleaned: dict[object, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            cleaned[key] = item
            continue
        override = overrides.get((model_type, key))
        if override is not None:
            result = override(item)
        else:
            field_info = model_type.model_fields.get(key)
            result = item if field_info is None else drop_unresolved(item, field_info.annotation, overrides)
        if result is not DROP:
            cleaned[key] = result
    return cleaned


def drop_unresolved(value: object, annotation: object, overrides: FieldOverrides) -> object:
    """Remove unresolved leaves from a value destined for ``annotation``; ``DROP`` when it is absent itself."""
    if is_unresolved(value):
        return DROP
    if annotation is object:
        return drop_unresolved_untyped(value)
    model_type = _model_annotation(annotation)
    if model_type is not None:
        return drop_unresolved_fields(value, model_type, overrides)
    for candidate in _annotation_options(annotation):
        origin = get_origin(candidate)
        arguments = get_args(candidate)
        if origin is dict and isinstance(value, Mapping) and len(arguments) == 2:
            value_type = arguments[1]
            cleaned: dict[object, object] = {}
            for key, item in value.items():
                result = drop_unresolved(item, value_type, overrides)
                if result is not DROP:
                    cleaned[key] = result
            return cleaned
        if origin is list and isinstance(value, list) and arguments:
            return [_drop_unresolved_list_item(item, arguments[0], overrides) for item in value]
    return value


def drop_unresolved_untyped(value: object) -> object:
    """Remove unresolved leaves from a value whose shape no model describes."""
    if is_unresolved(value):
        return DROP
    if isinstance(value, Mapping):
        cleaned: dict[object, object] = {}
        for key, item in value.items():
            result = drop_unresolved_untyped(item)
            if result is not DROP:
                cleaned[key] = result
        return cleaned
    if isinstance(value, list):
        return [_drop_unresolved_untyped_list_item(item) for item in value]
    return value


def _drop_unresolved_list_item(value: object, annotation: object, overrides: FieldOverrides) -> object:
    if isinstance(value, (Mapping, list)):
        result = drop_unresolved(value, annotation, overrides)
        return value if result is DROP else result
    return value


def _drop_unresolved_untyped_list_item(value: object) -> object:
    if isinstance(value, (Mapping, list)):
        return drop_unresolved_untyped(value)
    return value


def _annotation_options(annotation: object) -> tuple[object, ...]:
    if get_origin(annotation) in (Union, UnionType):
        return tuple(item for item in get_args(annotation) if item is not type(None))
    return (annotation,)


def _model_annotation(annotation: object) -> type[ClosedModel] | None:
    for candidate in _annotation_options(annotation):
        if isinstance(candidate, type) and issubclass(candidate, ClosedModel):
            return candidate
    return None
