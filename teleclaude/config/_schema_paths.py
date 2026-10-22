"""Resolve machine-configuration schema paths against their owning model."""

from __future__ import annotations

from enum import StrEnum
from types import UnionType
from typing import Any, Final, Union, get_args, get_origin

from teleclaude.config.tiers import Scope, effective_scope, pydantic_field_scope, pydantic_field_ungoverned_body

PATH_SEPARATOR: Final = "."
MODEL_FIELDS_ATTRIBUTE: Final = "model_fields"
_EMPTY_PATH_ERROR: Final = "Machine config path must not be empty."
_UNKNOWN_PATH_ERROR_TEMPLATE: Final = "Unknown machine config path: {path}"


def resolve_schema_scope(model_type: type[Any], path: str | tuple[str, ...]) -> Scope:
    """Resolve a declared schema path, including instances of dynamic containers."""
    parts = tuple(path.split(PATH_SEPARATOR)) if isinstance(path, str) else path
    if not parts:
        raise ValueError(_EMPTY_PATH_ERROR)
    inherited = Scope.LOCAL
    master_ancestor = False
    index = 0
    while index < len(parts):
        name = parts[index]
        fields = getattr(model_type, MODEL_FIELDS_ATTRIBUTE, None)
        if not isinstance(fields, dict) or name not in fields:
            raise ValueError(_UNKNOWN_PATH_ERROR_TEMPLATE.format(path=PATH_SEPARATOR.join(parts)))
        field_info = fields[name]
        inherited = effective_scope(pydantic_field_scope(field_info), inherited)
        master_ancestor = master_ancestor or inherited is Scope.MASTER
        index += 1
        if index == len(parts):
            return Scope.MASTER if master_ancestor else inherited
        annotation = field_info.annotation
        nested = _nested_model(annotation)
        if nested is not None:
            model_type = nested
            continue
        enum_member = _enum_member_model(annotation, parts[index])
        if enum_member is not None:
            model_type = enum_member
            index += 1
            if index == len(parts):
                return Scope.MASTER if master_ancestor else inherited
            continue
        if _is_ungoverned_container(annotation, field_info):
            return Scope.MASTER if master_ancestor else inherited
        raise ValueError(_UNKNOWN_PATH_ERROR_TEMPLATE.format(path=PATH_SEPARATOR.join(parts)))
    return Scope.MASTER if master_ancestor else inherited


def master_scoped_paths(model_type: type[Any]) -> tuple[tuple[str, ...], ...]:
    """Return minimal paths with master scope in a model's declared schema."""
    return tuple(_master_paths(model_type, Scope.LOCAL))


def _nested_model(annotation: Any) -> type[Any] | None:
    for candidate in _union_candidates(annotation):
        if candidate is type(None) or get_origin(candidate) in (dict, list):
            continue
        if isinstance(candidate, type) and isinstance(getattr(candidate, MODEL_FIELDS_ATTRIBUTE, None), dict):
            return candidate
    return None


def _is_ungoverned_container(annotation: Any, field_info: Any) -> bool:
    if not pydantic_field_ungoverned_body(field_info):
        return False
    return any(get_origin(candidate) in (dict, list) for candidate in _union_candidates(annotation))


def _enum_member_model(annotation: Any, key: str) -> type[Any] | None:
    for candidate in _union_candidates(annotation):
        if get_origin(candidate) is not dict:
            continue
        key_type, member_type = get_args(candidate)
        if (
            isinstance(key_type, type)
            and issubclass(key_type, StrEnum)
            and key in {item.value for item in key_type}
            and isinstance(member_type, type)
            and isinstance(getattr(member_type, MODEL_FIELDS_ATTRIBUTE, None), dict)
        ):
            return member_type
    return None


def _master_paths(model_type: type[Any], inherited_scope: Scope, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    paths: list[tuple[str, ...]] = []
    for name, field_info in model_type.model_fields.items():
        path = (*prefix, name)
        scope = effective_scope(pydantic_field_scope(field_info), inherited_scope)
        if scope is Scope.MASTER:
            paths.append(path)
            continue
        nested = _nested_model(field_info.annotation)
        if nested is not None:
            paths.extend(_master_paths(nested, scope, path))
            continue
        for candidate in _union_candidates(field_info.annotation):
            if get_origin(candidate) is dict:
                key_type, member_type = get_args(candidate)
                if isinstance(key_type, type) and issubclass(key_type, StrEnum):
                    nested_member = _nested_model(member_type)
                    if nested_member is not None:
                        for key in key_type:
                            paths.extend(_master_paths(nested_member, scope, (*path, key.value)))
    return paths


def _union_candidates(annotation: Any) -> tuple[Any, ...]:
    return get_args(annotation) if get_origin(annotation) in (Union, UnionType) else (annotation,)
