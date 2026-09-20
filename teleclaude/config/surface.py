"""Schema-owned descriptors for the machine configuration's public surface."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import StrEnum
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from teleclaude.config._models import TeleclaudeConfig
from teleclaude.config.tiers import (
    UNGOVERNED_BODY_METADATA_KEY,
    Tier,
    dataclass_field_is_sensitive,
    dataclass_field_tier,
    effective_tier,
)

_PATH_SEPARATOR = "."
_ENVIRONMENT_SEPARATOR = "_"


@dataclass(frozen=True)
class ConfigSurfaceDescriptor:
    """One statically declared machine-config leaf and its public-surface metadata."""

    path: tuple[str, ...]
    tier: Tier
    sensitive: bool
    environment_name: str | None

    @property
    def dotted_path(self) -> str:
        """Return the schema path used in diagnostics and operator-facing surfaces."""
        return _PATH_SEPARATOR.join(self.path)


def environment_name_for_path(path: tuple[str, ...]) -> str:
    """Derive the environment name declared by a sensitive schema leaf."""
    return _ENVIRONMENT_SEPARATOR.join(part.upper() for part in path)


def machine_config_surface() -> tuple[ConfigSurfaceDescriptor, ...]:
    """Return every statically declared machine-config leaf and its effective metadata."""
    return tuple(_walk_schema(TeleclaudeConfig, Tier.INTERNAL))


def _walk_schema(
    struct_type: type[Any], inherited_tier: Tier, prefix: tuple[str, ...] = ()
) -> list[ConfigSurfaceDescriptor]:
    """Walk schema-declared leaves, rejecting structured bodies without an owner declaration."""
    descriptors: list[ConfigSurfaceDescriptor] = []
    hints = get_type_hints(struct_type)
    for field in dataclasses.fields(struct_type):
        path = (*prefix, field.name)
        tier = effective_tier(dataclass_field_tier(field), inherited_tier)
        annotation = hints.get(field.name, field.type)
        nested = _nested_dataclass(annotation)
        if nested is not None:
            descriptors.extend(_walk_schema(nested, tier, path))
            continue
        enum_mapping = _enum_mapping(annotation)
        if enum_mapping is not None:
            key_type, member_type = enum_mapping
            for key in key_type:
                descriptors.extend(_walk_schema(member_type, tier, (*path, key.value)))
            continue
        structured_member = _structured_container_member(annotation)
        if structured_member is not None:
            _require_ungoverned_body(field, path, structured_member)
        sensitive = dataclass_field_is_sensitive(field)
        descriptors.append(
            ConfigSurfaceDescriptor(
                path=path,
                tier=tier,
                sensitive=sensitive,
                environment_name=environment_name_for_path(path) if sensitive else None,
            )
        )
    return descriptors


def _nested_dataclass(annotation: Any) -> type[Any] | None:
    """Return an optional nested dataclass annotation, excluding container members."""
    candidates = get_args(annotation) if get_origin(annotation) in (Union, UnionType) else (annotation,)
    for candidate in candidates:
        if candidate is type(None) or get_origin(candidate) in (dict, list):
            continue
        if isinstance(candidate, type) and dataclasses.is_dataclass(candidate):
            return candidate
    return None


def _structured_container_member(annotation: Any) -> type[Any] | None:
    """Return a container's structured member type when static leaf discovery cannot reach it."""
    candidates = get_args(annotation) if get_origin(annotation) in (Union, UnionType) else (annotation,)
    for candidate in candidates:
        if get_origin(candidate) not in (dict, list):
            continue
        for member in get_args(candidate):
            if isinstance(member, type) and dataclasses.is_dataclass(member):
                return member
    return None


def _enum_mapping(annotation: Any) -> tuple[type[StrEnum], type[Any]] | None:
    """Return a closed enum-keyed mapping and its dataclass value type."""
    candidates = get_args(annotation) if get_origin(annotation) in (Union, UnionType) else (annotation,)
    for candidate in candidates:
        if get_origin(candidate) is not dict:
            continue
        key_type, value_type = get_args(candidate)
        if (
            isinstance(key_type, type)
            and issubclass(key_type, StrEnum)
            and isinstance(value_type, type)
            and dataclasses.is_dataclass(value_type)
        ):
            return key_type, value_type
    return None


def _require_ungoverned_body(field: dataclasses.Field[object], path: tuple[str, ...], member_type: type[Any]) -> None:
    """Fail when a structured container has neither static members nor an explicit owner."""
    reason = field.metadata.get(UNGOVERNED_BODY_METADATA_KEY)
    if isinstance(reason, str) and reason.strip():
        return
    dotted_path = _PATH_SEPARATOR.join(path)
    raise TypeError(
        f"Schema field `{dotted_path}` contains `{member_type.__name__}` members that cannot be statically walked; "
        f"declare `{UNGOVERNED_BODY_METADATA_KEY}` with a non-empty reason or model its members explicitly."
    )
