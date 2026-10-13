"""The effective view of one configuration subject: references resolved, secrets masked.

Each section resolves its environment references from the environment its configuration surface
owns and leaves out a whole-value reference that has no value there, exactly as the loader does.
Every set value of a field its model declares ``SENSITIVE`` is masked. The stored documents and
their revisions are untouched; this view is for reading only.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import UnionType
from typing import Annotated, Final, Union, cast, get_args, get_origin

from pydantic import TypeAdapter, ValidationError

from teleclaude.closed_model import MASKED_INPUT, ClosedModel, field_is_sensitive, mask_sensitive_values
from teleclaude.config._environment import (
    expand_environment_references,
    find_environment_references,
    read_environment_file,
    whole_reference_name,
)
from teleclaude.config._machine_build import drop_unresolved_machine_fields
from teleclaude.config._models import TeleclaudeConfig
from teleclaude.config._unresolved import NO_OVERRIDES, drop_unresolved_fields
from teleclaude.config.identity_schema import PersonEntry
from teleclaude.config.machine_environment import machine_runtime_environment
from teleclaude.config.operation_answers import EnvironmentReferenceRow
from teleclaude.config.person_resource import IDENTITY_SECTION, OVERLAY_PATCH_KEY, SETTINGS_SECTION
from teleclaude.config.resource_contract import SubjectView
from teleclaude.config.schema import CompanyConfig, GlobalConfig, PersonConfig, ProjectConfig
from teleclaude.config_subjects import ConfigEnvironment, ConfigSubjectKind
from teleclaude.paths import ConfigFileName


@dataclass(frozen=True)
class _SectionBinding:
    """How one section of a subject view resolves: its model and its owning environment."""

    model: type[ClosedModel]
    source_index: int
    owner_only: bool


_TIER_BINDINGS: Final[Mapping[ConfigSubjectKind, _SectionBinding]] = {
    ConfigSubjectKind.GLOBAL: _SectionBinding(GlobalConfig, 0, owner_only=False),
    ConfigSubjectKind.PROJECT: _SectionBinding(ProjectConfig, 0, owner_only=False),
    ConfigSubjectKind.COMPANY: _SectionBinding(CompanyConfig, 0, owner_only=True),
}

_PERSON_BINDINGS: Final[Mapping[str, _SectionBinding]] = {
    IDENTITY_SECTION: _SectionBinding(PersonEntry, 0, owner_only=False),
    SETTINGS_SECTION: _SectionBinding(PersonConfig, 1, owner_only=True),
}


_TYPED_SCALARS: Final = (bool, int, float)
_INVALID_VALUE_MESSAGE: Final = "Configuration value at '{location}' does not satisfy its declared type"
_PATH_SEPARATOR: Final = "."


class InvalidEffectiveValue(ValueError):
    """A resolved configuration value is rejected by its declared field type."""


_PATCH_MODELS: Final[Mapping[ConfigSubjectKind, tuple[type[ClosedModel], ...]]] = {
    ConfigSubjectKind.COMPUTER: (TeleclaudeConfig,),
    ConfigSubjectKind.GLOBAL: (GlobalConfig,),
    ConfigSubjectKind.PROJECT: (ProjectConfig,),
    ConfigSubjectKind.COMPANY: (CompanyConfig,),
    ConfigSubjectKind.PERSON: (PersonEntry, PersonConfig),
}


def effective_sections(view: SubjectView) -> dict[str, object]:  # guard: loose-dict - rendered config view
    """Return the view's sections with references resolved and sensitive values masked."""
    return _EFFECTIVE_SECTIONS[view.ref.kind](view)


def environment_references(view: SubjectView) -> list[EnvironmentReferenceRow]:
    """Every field of a computer, global, or person view whose stored value is one whole environment reference.

    Resolved from the environment its section's configuration surface owns, the way the effective
    view resolves. A reference with no value there is listed although the effective view leaves its
    field out; the value itself is never carried.
    """
    entries: list[EnvironmentReferenceRow] = []
    for name, section in view.sections.items():
        owner = _reference_owner(view, name)
        if owner is None:
            continue
        environment, environment_name = owner
        for reference in find_environment_references(section):
            leaf = _value_at(section, reference.path)
            if not isinstance(leaf, str) or whole_reference_name(leaf) is None:
                continue
            entries.append(
                EnvironmentReferenceRow(
                    path=_PATH_SEPARATOR.join((name, *(str(part) for part in reference.path))),
                    variable=reference.name,
                    environment=environment_name,
                    has_value=reference.name in environment or reference.default is not None,
                )
            )
    return entries


def _reference_owner(view: SubjectView, section_name: str) -> tuple[Mapping[str, str], ConfigEnvironment] | None:
    """The environment values and the environment name that own a section's references, if the kind projects any."""
    match view.ref.kind:
        case ConfigSubjectKind.COMPUTER:
            return machine_runtime_environment(), ConfigEnvironment.MACHINE
        case ConfigSubjectKind.GLOBAL:
            return _environment_beside(view, 0, owner_only=False), ConfigEnvironment.GLOBAL
        case ConfigSubjectKind.PERSON:
            if section_name == IDENTITY_SECTION:
                return _environment_beside(view, 0, owner_only=False), ConfigEnvironment.GLOBAL
            return _environment_beside(view, 1, owner_only=True), ConfigEnvironment.PERSON
        case _:
            return None


def _environment_beside(view: SubjectView, source_index: int, *, owner_only: bool) -> Mapping[str, str]:
    return read_environment_file(view.sources[source_index].with_name(ConfigFileName.ENV), owner_only=owner_only)


def _value_at(document: object, path: tuple[str | int, ...]) -> object:
    current = document
    for part in path:
        if isinstance(current, Mapping):
            current = current.get(part)
        elif isinstance(current, list) and isinstance(part, int):
            current = current[part]
        else:
            return None
    return current


def without_masked_values(
    kind: ConfigSubjectKind, patch: Mapping[str, object]
) -> dict[str, object]:  # guard: loose-dict - caller-supplied RFC 7386 patch document
    """Return the patch minus every sensitive leaf still carrying the mask the view rendered.

    A patch built from the effective view then leaves each stored secret as it is.
    """
    if kind is ConfigSubjectKind.PERSON and isinstance(patch.get(OVERLAY_PATCH_KEY), Mapping):
        overlay = cast(Mapping[str, object], patch[OVERLAY_PATCH_KEY])  # guard: loose-dict - caller patch
        rest = {key: value for key, value in patch.items() if key != OVERLAY_PATCH_KEY}
        return {
            **_without_masked(rest, _PATCH_MODELS[kind]),
            OVERLAY_PATCH_KEY: _without_masked(overlay, (PersonConfig,)),
        }
    return _without_masked(patch, _PATCH_MODELS[kind])


def _without_masked(
    value: Mapping[str, object], models: tuple[type[ClosedModel], ...]
) -> dict[str, object]:  # guard: loose-dict - caller-supplied RFC 7386 patch document
    kept: dict[str, object] = {}  # guard: loose-dict - caller-supplied RFC 7386 patch document
    for key, item in value.items():
        field_info = next((model.model_fields[key] for model in models if key in model.model_fields), None)
        if field_info is None:
            kept[key] = item
        elif field_is_sensitive(field_info):
            if item != MASKED_INPUT:
                kept[key] = item
        else:
            kept[key] = _without_masked_nested(item, field_info.annotation)
    return kept


def _without_masked_nested(value: object, annotation: object) -> object:
    nested = _nested_models(annotation)
    if not nested:
        return value
    if isinstance(value, Mapping):
        return _without_masked(value, nested)
    if isinstance(value, list):
        return [_without_masked(item, nested) if isinstance(item, Mapping) else item for item in value]
    return value


def _nested_models(annotation: object) -> tuple[type[ClosedModel], ...]:
    """The closed models an annotation holds directly, in an optional or annotated union, or as list items."""
    models: list[type[ClosedModel]] = []
    for option in _options(annotation):
        candidates = _options(get_args(option)[0]) if get_origin(option) is list and get_args(option) else (option,)
        models.extend(
            candidate for candidate in candidates if isinstance(candidate, type) and issubclass(candidate, ClosedModel)
        )
    return tuple(models)


def _computer_sections(view: SubjectView) -> dict[str, object]:  # guard: loose-dict - rendered config view
    environment = machine_runtime_environment()
    return {
        name: _resolved_masked(section, environment, TeleclaudeConfig, drop_unresolved_machine_fields)
        for name, section in view.sections.items()
    }


def _tier_sections(view: SubjectView) -> dict[str, object]:  # guard: loose-dict - rendered config view
    binding = _TIER_BINDINGS[view.ref.kind]
    return {name: _bound_section(view, section, binding) for name, section in view.sections.items()}


def _person_sections(view: SubjectView) -> dict[str, object]:  # guard: loose-dict - rendered config view
    return {
        name: _bound_section(view, section, _PERSON_BINDINGS[name]) if name in _PERSON_BINDINGS else section
        for name, section in view.sections.items()
    }


def _bound_section(view: SubjectView, section: object, binding: _SectionBinding) -> object:
    source: Path = view.sources[binding.source_index]
    environment = read_environment_file(source.with_name(ConfigFileName.ENV), owner_only=binding.owner_only)
    return _resolved_masked(section, environment, binding.model, _drop_unresolved_tier_fields)


def _drop_unresolved_tier_fields(value: object, model_type: type[ClosedModel]) -> object:
    return drop_unresolved_fields(value, model_type, NO_OVERRIDES)


def _resolved_masked(
    section: object,
    environment: Mapping[str, str],
    model: type[ClosedModel],
    drop_unresolved: Callable[[object, type[ClosedModel]], object],
) -> object:
    resolved = expand_environment_references(section, environment, preserve_unresolved=True)
    return mask_sensitive_values(model, _typed_scalars(drop_unresolved(resolved, model), model, ()))


def typed_value(value: str, annotation: object, path: tuple[str | int, ...] = ()) -> object:
    """Give text the boolean or numeric meaning its declared type assigns; other text stays text.

    Raises ``InvalidEffectiveValue`` naming the path, never the value, when the type rejects it.
    """
    if not any(isinstance(base, type) and base in _TYPED_SCALARS for base in _options(annotation)):
        return value
    try:
        typed: object = TypeAdapter(annotation).validate_python(value)
    except ValidationError as error:
        location = _PATH_SEPARATOR.join(str(part) for part in path)
        raise InvalidEffectiveValue(_INVALID_VALUE_MESSAGE.format(location=location)) from error
    return typed if isinstance(typed, _TYPED_SCALARS) else value


def _typed_scalars(value: object, annotation: object, path: tuple[str | int, ...]) -> object:
    """Render plain values, giving each text the boolean or numeric meaning its declared field type assigns it."""
    if isinstance(value, str):
        return typed_value(str(value), annotation, path)
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, Mapping):
        nested = _nested_models(annotation)
        value_annotation = _mapping_value_annotation(annotation)
        return {
            str(key): _typed_field(key, item, nested, (*path, str(key)))
            if nested
            else _typed_scalars(item, value_annotation, (*path, str(key)))
            for key, item in value.items()
        }
    if isinstance(value, list):
        item_annotation = _list_item_annotation(annotation)
        return [_typed_scalars(item, item_annotation, (*path, index)) for index, item in enumerate(value)]
    return value


def _typed_field(
    key: object, value: object, models: tuple[type[ClosedModel], ...], path: tuple[str | int, ...]
) -> object:
    for model in models:
        if isinstance(key, str) and key in model.model_fields:
            return _typed_scalars(value, model.model_fields[key].rebuild_annotation(), path)
    return _typed_scalars(value, object, path)


def _list_item_annotation(annotation: object) -> object:
    for option in _options(annotation):
        if get_origin(option) is list and get_args(option):
            return get_args(option)[0]
    return object


def _mapping_value_annotation(annotation: object) -> object:
    for option in _options(annotation):
        if get_origin(option) is dict and len(get_args(option)) == 2:
            return get_args(option)[1]
    return object


def _options(annotation: object) -> tuple[object, ...]:
    """The alternatives an annotation admits, with ``Annotated`` metadata and unions unwrapped."""
    if get_origin(annotation) is Annotated:
        return _options(get_args(annotation)[0])
    if get_origin(annotation) in (Union, UnionType):
        return tuple(option for argument in get_args(annotation) for option in _options(argument))
    return (annotation,)


type _RenderedSections = dict[str, object]  # guard: loose-dict - rendered config view

_EFFECTIVE_SECTIONS: Final[Mapping[ConfigSubjectKind, Callable[[SubjectView], _RenderedSections]]] = {
    ConfigSubjectKind.COMPUTER: _computer_sections,
    ConfigSubjectKind.GLOBAL: _tier_sections,
    ConfigSubjectKind.PROJECT: _tier_sections,
    ConfigSubjectKind.COMPANY: _tier_sections,
    ConfigSubjectKind.PERSON: _person_sections,
}
