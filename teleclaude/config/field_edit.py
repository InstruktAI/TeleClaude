"""Compile schema-addressed editor intent into an owner operation."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any, cast, get_args

from pydantic import BaseModel

from teleclaude.closed_model import MASKED_INPUT
from teleclaude.config._defaults import DEFAULT_CONFIG
from teleclaude.config._environment import prepare_environment_value, read_environment_transaction
from teleclaude.config.editor_models import partial_model
from teleclaude.config.editor_view import editor_fields, editor_revision, person_secret_editor_fields
from teleclaude.config.effective_view import effective_sections, environment_references
from teleclaude.config.loader import validate_tier_candidate
from teleclaude.config.machine import config_path
from teleclaude.config.machine_config_mutation import (
    MachineConfigOperation,
    prepare_machine_mutation_transaction,
)
from teleclaude.config.machine_environment import machine_runtime_environment, machine_runtime_environment_snapshot
from teleclaude.config.migrations._chain import upcast
from teleclaude.config.operation_answers import (
    EditorFieldAnswer,
    EditorInputKind,
    EditorValueState,
    EnvironmentReferenceRow,
)
from teleclaude.config.operation_requests import ConfigEditIntent, Payload
from teleclaude.config.person_resource import OVERLAY_PATCH_KEY, SETTINGS_SECTION, person_overlay_path
from teleclaude.config.person_secrets import (
    list_person_mcp_secret_inventory,
    person_secret_store_creation_mode,
    person_secret_store_path,
    person_secret_store_revision,
)
from teleclaude.config.resource_catalog import load_mapping
from teleclaude.config.resource_contract import CommitEntry, SubjectView, commit_documents
from teleclaude.config.revision import StaleRevision
from teleclaude.config.schema import ConfigKind, PersonConfig
from teleclaude.config.transaction_views import read_subject_in_transactions
from teleclaude.config_subjects import ConfigEnvironment, ConfigSubjectKind, SubjectRef
from teleclaude.file_transaction import FileTransaction, file_transaction
from teleclaude.paths import GLOBAL_CONFIG_PATH, PROJECT_ENV_PATH, ConfigFileName

_KEY_SEPARATOR = "."
_COMPUTER_PREFIX = "computer."
_IDENTITY_PREFIX = "identity."
_OVERLAY_PREFIX = "overlay."
_SECRET_PREFIX = "secrets."
_SETTINGS_REFERENCE_PREFIX = f"{SETTINGS_SECTION}."
_INVALID_FIELD_ID = "the editor field identity is not present or editable"
_INVALID_FIELD_VALUE = "the entered value does not match the field's declared input type"
_INVALID_FIELD_ACTION = "the field edit intent is incomplete"
_MISSING_DEFAULT = object()
_GLOBAL_ENVIRONMENT = ConfigEnvironment.GLOBAL
_MACHINE_ENVIRONMENT = ConfigEnvironment.MACHINE
_PERSON_ENVIRONMENT = ConfigEnvironment.PERSON
_GLOBAL_ENV_NAME = ConfigFileName.ENV
_OVERLAY_SLUG = "slug"
_OVERLAY_KIND = "kind"
_SCHEMA_VERSION_KEY = "schema_version"
_KIND_KEY = "kind"
_COMPUTER_SECTION_KEY = "computer"
_MAPPING_TYPE = dict
_LIST_TYPE = list
_LIST_SEPARATOR = ","
_MASTER_SCOPED_KEY = "master_scoped_not_applicable"
_JSON_MODE = "json"
_EMPTY_TEXT = ""


class _BooleanText(StrEnum):
    TRUE = "true"
    FALSE = "false"


@dataclass(frozen=True)
class FieldEditPlan:
    """A validated field target and its one storage action."""

    field: EditorFieldAnswer
    intent: ConfigEditIntent
    value: object
    reference: EnvironmentReferenceRow | None
    patch: Payload | None
    unchanged: bool


def compile_field_edit(
    view: SubjectView,
    fields: list[EditorFieldAnswer],
    references: list[EnvironmentReferenceRow],
    field_id: str,
    intent: ConfigEditIntent | None,
    value: object,
) -> FieldEditPlan:
    """Validate the declared field identity and map edit intent to owner storage semantics."""
    field = next((candidate for candidate in fields if candidate.identity == field_id), None)
    if field is None or not field.editable:
        raise ValueError(_INVALID_FIELD_ID)
    if intent is None:
        raise ValueError(_INVALID_FIELD_ACTION)
    reference = _reference_for_field(view.ref.kind, field.identity, references)
    if intent is ConfigEditIntent.KEEP:
        return FieldEditPlan(field, intent, field.value, reference, None, True)
    if value == MASKED_INPUT:
        return FieldEditPlan(field, ConfigEditIntent.KEEP, field.value, reference, None, True)
    next_value = None if intent is ConfigEditIntent.CLEAR else _coerce(field, value)
    if reference is not None:
        unchanged = intent is ConfigEditIntent.REPLACE and next_value == field.value
        return FieldEditPlan(field, intent, next_value, reference, None, unchanged)
    unchanged = (intent is ConfigEditIntent.REPLACE and next_value == field.value) or (
        intent is ConfigEditIntent.CLEAR and (field.value is None or field.value_state is EditorValueState.DEFAULT)
    )
    patch = _patch_for_field(view, field, next_value, references, remove=intent is ConfigEditIntent.CLEAR)
    return FieldEditPlan(field, intent, next_value, None, patch, unchanged)


def environment_value(plan: FieldEditPlan) -> str | None:
    """Render an already-typed field value as the text held by its reference variable."""
    if plan.value is None:
        return None
    if isinstance(plan.value, bool):
        return _BooleanText.TRUE.value if plan.value else _BooleanText.FALSE.value
    if isinstance(plan.value, str | int | float):
        return str(plan.value)
    raise ValueError(_INVALID_FIELD_VALUE)


def environment_for_reference(reference: EnvironmentReferenceRow) -> ConfigEnvironment:
    """Return the existing environment owner carried by a configuration reference."""
    return reference.environment


def apply_reference_edit(
    ref: SubjectRef,
    field_id: str,
    intent: ConfigEditIntent,
    value: object,
    expected_editor_revision: str,
) -> bool:
    """Apply one referenced-field edit under the subject and environment locks it can change."""
    environment_paths = _environment_paths(ref)
    document_paths = _document_paths(ref)
    ordered_paths = (*document_paths, *environment_paths)
    transactions: dict[Path, FileTransaction] = {}
    with ExitStack() as stack:
        for path in ordered_paths:
            if path not in transactions:
                transactions[path] = stack.enter_context(file_transaction(path))
        view = read_subject_in_transactions(ref, transactions)
        environment_values = _environment_values(ref, transactions)
        machine_environment = (
            machine_runtime_environment_snapshot(environment_values[_MACHINE_ENVIRONMENT])
            if _MACHINE_ENVIRONMENT in environment_values
            else None
        )
        outside = view.read_only.get(_MASTER_SCOPED_KEY, [])
        outside_scope = tuple(str(item) for item in outside) if isinstance(outside, list) else ()
        references = environment_references(view, machine_environment=machine_environment)
        fields = editor_fields(
            ref.kind,
            effective_sections(view, machine_environment=machine_environment),
            outside_scope,
            source_sections=view.sections,
            references=references,
        )
        personal_secret_digest: str | None = None
        if ref.kind is ConfigSubjectKind.PERSON and ref.instance is not None:
            fields.extend(person_secret_editor_fields(list_person_mcp_secret_inventory(ref.instance)))
            secret_path = person_secret_store_path(ref.instance)
            personal_secret_digest = person_secret_store_revision(
                ref.instance, content=transactions[secret_path].read_text()
            )
        plan = compile_field_edit(view, fields, references, field_id, intent, value)
        active_environment = environment_values.get(plan.reference.environment) if plan.reference is not None else None
        if plan.reference is None or active_environment is None:
            raise ValueError(_INVALID_FIELD_ID)
        current_revision = editor_revision(
            view,
            machine_environment=machine_environment,
            environment_overrides=environment_values,
            personal_secret_digest=personal_secret_digest,
        )
        if current_revision != expected_editor_revision:
            raise StaleRevision(expected=expected_editor_revision, actual=current_revision)
        variable = plan.reference.variable
        next_value = environment_value(plan)
        if intent is ConfigEditIntent.KEEP or plan.unchanged:
            return False
        if intent is ConfigEditIntent.CLEAR and variable not in active_environment:
            return False
        if intent is ConfigEditIntent.REPLACE and active_environment.get(variable) == next_value:
            return False
        candidate_environment = dict(active_environment)
        if next_value is None:
            candidate_environment.pop(variable, None)
        else:
            candidate_environment[variable] = next_value
        if not field_id.startswith(_SECRET_PREFIX):
            _validate_staged_environment(ref, view, plan.reference.environment, candidate_environment, transactions)
        path = _environment_path(ref, plan.reference.environment)
        transaction = transactions[path]
        candidate_text = prepare_environment_value(transaction, variable, next_value)
        creation_mode = (
            person_secret_store_creation_mode(path) if plan.reference.environment is _PERSON_ENVIRONMENT else None
        )
        commit_documents(
            [
                CommitEntry(
                    transaction=transaction,
                    committed_text=transaction.read_text(),
                    candidate_text=candidate_text,
                    creation_mode=creation_mode,
                )
            ]
        )
    if ref.kind is ConfigSubjectKind.COMPUTER:
        machine_runtime_environment()
    return True


def _document_paths(ref: SubjectRef) -> tuple[Path, ...]:
    if ref.kind is ConfigSubjectKind.COMPUTER:
        return (config_path,)
    if ref.kind is ConfigSubjectKind.PERSON and ref.instance is not None:
        return (GLOBAL_CONFIG_PATH, person_overlay_path(ref.instance))
    if ref.kind is ConfigSubjectKind.GLOBAL:
        return (GLOBAL_CONFIG_PATH,)
    raise ValueError(_INVALID_FIELD_ID)


def _environment_paths(ref: SubjectRef) -> tuple[Path, ...]:
    if ref.kind is ConfigSubjectKind.COMPUTER:
        return (PROJECT_ENV_PATH,)
    if ref.kind is ConfigSubjectKind.PERSON and ref.instance is not None:
        return (GLOBAL_CONFIG_PATH.with_name(_GLOBAL_ENV_NAME), person_secret_store_path(ref.instance))
    if ref.kind is ConfigSubjectKind.GLOBAL:
        return (GLOBAL_CONFIG_PATH.with_name(_GLOBAL_ENV_NAME),)
    raise ValueError(_INVALID_FIELD_ID)


def _environment_path(ref: SubjectRef, environment: ConfigEnvironment) -> Path:
    match environment:
        case ConfigEnvironment.MACHINE:
            return PROJECT_ENV_PATH
        case ConfigEnvironment.GLOBAL:
            return GLOBAL_CONFIG_PATH.with_name(_GLOBAL_ENV_NAME)
        case ConfigEnvironment.PERSON:
            if ref.instance is None:
                raise ValueError(_INVALID_FIELD_ID)
            return person_secret_store_path(ref.instance)


def _environment_values(
    ref: SubjectRef, transactions: Mapping[Path, FileTransaction]
) -> dict[ConfigEnvironment, dict[str, str]]:
    values: dict[ConfigEnvironment, dict[str, str]] = {}
    for environment in _environments_for_subject(ref):
        path = _environment_path(ref, environment)
        values[environment] = read_environment_transaction(
            transactions[path], owner_only=environment is ConfigEnvironment.PERSON
        )
    return values


def _environments_for_subject(ref: SubjectRef) -> tuple[ConfigEnvironment, ...]:
    if ref.kind is ConfigSubjectKind.COMPUTER:
        return (_MACHINE_ENVIRONMENT,)
    if ref.kind is ConfigSubjectKind.PERSON:
        return (_GLOBAL_ENVIRONMENT, _PERSON_ENVIRONMENT)
    if ref.kind is ConfigSubjectKind.GLOBAL:
        return (_GLOBAL_ENVIRONMENT,)
    raise ValueError(_INVALID_FIELD_ID)


def _validate_staged_environment(
    ref: SubjectRef,
    view: SubjectView,
    environment: ConfigEnvironment,
    candidate_environment: Mapping[str, str],
    transactions: Mapping[Path, FileTransaction],
) -> None:
    if ref.kind is ConfigSubjectKind.COMPUTER:
        env_values = machine_runtime_environment_snapshot(candidate_environment)
        prepare_machine_mutation_transaction(
            transactions[config_path],
            MachineConfigOperation.PATCH,
            lambda raw: raw,
            expected_revision=view.revision,
            environment=env_values,
        )
        return
    if ref.kind is ConfigSubjectKind.PERSON and ref.instance is not None:
        if environment is _PERSON_ENVIRONMENT:
            settings = view.sections.get(SETTINGS_SECTION)
            settings_mapping = settings if isinstance(settings, Mapping) else {}
            validate_tier_candidate(
                person_overlay_path(ref.instance),
                ConfigKind.PERSON,
                {**settings_mapping, _OVERLAY_SLUG: ref.instance},
                environment_override=candidate_environment,
            )
            return
        global_transaction = transactions[GLOBAL_CONFIG_PATH]
        stored = load_mapping(global_transaction.read_text(), GLOBAL_CONFIG_PATH)
        raw = dict(upcast(stored, SubjectRef(ConfigSubjectKind.GLOBAL)))
        candidate = {key: item for key, item in raw.items() if key not in {_KIND_KEY, _SCHEMA_VERSION_KEY}}
        validate_tier_candidate(
            GLOBAL_CONFIG_PATH,
            ConfigKind.GLOBAL,
            candidate,
            environment_override=candidate_environment,
        )
        return


def _coerce(field: EditorFieldAnswer, value: object) -> object:
    kind = field.input_kind
    if kind is EditorInputKind.BOOLEAN:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value in (_BooleanText.TRUE, _BooleanText.FALSE):
            return value == _BooleanText.TRUE
        raise ValueError(_INVALID_FIELD_VALUE)
    if kind is EditorInputKind.INTEGER:
        if isinstance(value, bool):
            raise ValueError(_INVALID_FIELD_VALUE)
        try:
            return int(value) if isinstance(value, str | int) else _raise_invalid()
        except (TypeError, ValueError) as error:
            raise ValueError(_INVALID_FIELD_VALUE) from error
    if kind is EditorInputKind.NUMBER:
        if isinstance(value, bool):
            raise ValueError(_INVALID_FIELD_VALUE)
        try:
            return float(value) if isinstance(value, str | int | float) else _raise_invalid()
        except (TypeError, ValueError) as error:
            raise ValueError(_INVALID_FIELD_VALUE) from error
    if kind is EditorInputKind.ENUM:
        if not isinstance(value, str) or value not in field.choices:
            raise ValueError(_INVALID_FIELD_VALUE)
        return value
    if kind is EditorInputKind.STRING:
        if not isinstance(value, str):
            raise ValueError(_INVALID_FIELD_VALUE)
        return value
    if kind in (EditorInputKind.STRING_LIST, EditorInputKind.VALUE_LIST):
        if isinstance(value, str):
            return [item.strip() for item in value.split(_LIST_SEPARATOR) if item.strip()]
        if not isinstance(value, list):
            raise ValueError(_INVALID_FIELD_VALUE)
        if kind is EditorInputKind.STRING_LIST and any(not isinstance(item, str) for item in value):
            raise ValueError(_INVALID_FIELD_VALUE)
        return value
    if kind is EditorInputKind.JSON:
        return value
    raise ValueError(_INVALID_FIELD_VALUE)


def _raise_invalid() -> Any:
    raise ValueError(_INVALID_FIELD_VALUE)


def _reference_for_field(
    kind: ConfigSubjectKind,
    field_id: str,
    references: list[EnvironmentReferenceRow],
) -> EnvironmentReferenceRow | None:
    if field_id.startswith(_SECRET_PREFIX):
        return EnvironmentReferenceRow(
            path=field_id,
            variable=field_id.removeprefix(_SECRET_PREFIX),
            environment=ConfigEnvironment.PERSON,
            has_value=True,
        )
    path = field_id
    if kind is ConfigSubjectKind.COMPUTER:
        path = f"{_COMPUTER_PREFIX}{field_id}"
    if field_id.startswith(_OVERLAY_PREFIX):
        path = f"{_SETTINGS_REFERENCE_PREFIX}{field_id.removeprefix(_OVERLAY_PREFIX + _KEY_SEPARATOR)}"
    return next((reference for reference in references if reference.path == path), None)


def _patch_for_field(
    view: SubjectView,
    field: EditorFieldAnswer,
    value: object,
    references: list[EnvironmentReferenceRow],
    *,
    remove: bool,
) -> Payload:
    if view.ref.kind is ConfigSubjectKind.COMPUTER:
        path = field.identity
        parts = tuple(path.split(_KEY_SEPARATOR))
        if any(segment.isdigit() for segment in parts):
            return _machine_list_patch(view, parts, value, remove=remove)
        default = _default_for(parts)
        stored_value = None if default is not _MISSING_DEFAULT and value == default else value
        return _nested_patch(parts, stored_value)
    if view.ref.kind is ConfigSubjectKind.PERSON and field.identity.startswith(_IDENTITY_PREFIX):
        return _nested_patch(tuple(field.identity.removeprefix(_IDENTITY_PREFIX).split(_KEY_SEPARATOR)), value)
    if view.ref.kind is ConfigSubjectKind.PERSON and field.identity.startswith(_OVERLAY_PREFIX):
        slug = view.ref.instance
        if slug is None:
            raise ValueError(_INVALID_FIELD_ID)
        settings = view.sections.get(SETTINGS_SECTION)
        settings_mapping = settings if isinstance(settings, Mapping) else {}
        overlay = partial_model(
            PersonConfig, {**settings_mapping, _OVERLAY_SLUG: slug, _OVERLAY_KIND: ConfigKind.PERSON}
        )
        referenced = {
            item.path.removeprefix(_SETTINGS_REFERENCE_PREFIX)
            for item in references
            if item.path.startswith(_SETTINGS_REFERENCE_PREFIX)
        }
        return {
            OVERLAY_PATCH_KEY: _overlay_patch(
                overlay,
                tuple(field.identity.removeprefix(_OVERLAY_PREFIX).lstrip(_KEY_SEPARATOR).split(_KEY_SEPARATOR)),
                value,
                referenced,
            )
        }
    raise ValueError(_INVALID_FIELD_ID)


def _machine_list_patch(view: SubjectView, parts: tuple[str, ...], value: object, *, remove: bool) -> Payload:
    index_position = next(position for position, segment in enumerate(parts) if segment.isdigit())
    list_path = parts[:index_position]
    list_index = int(parts[index_position])
    document = view.sections.get(_COMPUTER_SECTION_KEY)
    collection_value = _value_at(document, list_path)
    if not isinstance(collection_value, list) or list_index >= len(collection_value):
        raise ValueError(_INVALID_FIELD_ID)
    collection = deepcopy(collection_value)
    target = collection[list_index]
    if not isinstance(target, Mapping):
        raise ValueError(_INVALID_FIELD_ID)
    target_copy = dict(target)
    leaf_path = parts[index_position + 1 :]
    _set_mapping_value(target_copy, leaf_path, value, remove=remove)
    collection[list_index] = target_copy
    return _nested_patch(list_path, collection)


def _value_at(document: object, path: tuple[str, ...]) -> object:
    current = document
    for segment in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(segment)
    return current


# guard: loose-dict-func - This focused recursive update follows a schema-verified path in one YAML field tree.
def _set_mapping_value(document: dict[str, object], path: tuple[str, ...], value: object, *, remove: bool) -> None:
    cursor = document
    for segment in path[:-1]:
        child = cursor.get(segment)
        if not isinstance(child, Mapping):
            raise ValueError(_INVALID_FIELD_ID)
        mutable_child = dict(child)
        cursor[segment] = mutable_child
        cursor = mutable_child
    if remove:
        cursor.pop(path[-1], None)
    else:
        cursor[path[-1]] = value


def _default_for(path: tuple[str, ...]) -> object:
    current: object = DEFAULT_CONFIG
    for segment in path:
        if not isinstance(current, Mapping) or segment not in current:
            return _MISSING_DEFAULT
        current = current[segment]
    return current


def _nested_patch(parts: tuple[str, ...], value: object) -> Payload:
    leaf = value.value if isinstance(value, Enum) else value
    patch: Payload = {parts[-1]: leaf}
    for part in reversed(parts[:-1]):
        patch = {part: patch}
    return patch


def _covered_by_reference(path: str, referenced: set[str]) -> bool:
    return any(reference == path or reference.startswith(f"{path}{_KEY_SEPARATOR}") for reference in referenced)


def _zero_value(annotation: Any) -> Any:
    for candidate in get_args(annotation) or (annotation,):
        if candidate is type(None):
            continue
        if candidate is str:
            return _EMPTY_TEXT
        if candidate is bool:
            return False
        if candidate is int:
            return 0
        if candidate is float:
            return 0.0
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return _blank_model(candidate)
        return None
    return None


def _blank_model(model_type: type[BaseModel]) -> BaseModel:
    values = {
        name: _zero_value(field_info.annotation)
        for name, field_info in model_type.model_fields.items()
        if field_info.is_required()
    }
    return model_type.model_validate(values)


def _overlay_patch(overlay: BaseModel, parts: tuple[str, ...], value: object, referenced: set[str]) -> Payload:
    patch: Payload = {}
    cursor = patch
    node: BaseModel | None = overlay
    for depth, part in enumerate(parts[:-1]):
        child = getattr(node, part, None) if node is not None else None
        if child is None and node is not None:
            annotation = type(node).model_fields[part].annotation
            candidates = get_args(annotation) or (annotation,)
            nested = next(
                candidate
                for candidate in candidates
                if candidate is not type(None) and isinstance(candidate, type) and issubclass(candidate, BaseModel)
            )
            child = _blank_model(nested)
            parent_path = _KEY_SEPARATOR.join(parts[: depth + 1])
            seeded = {
                key: item
                for key, item in child.model_dump(mode=_JSON_MODE, exclude_none=True).items()
                if not _covered_by_reference(f"{parent_path}{_KEY_SEPARATOR}{key}", referenced)
            }
            cursor[part] = seeded
            cursor = seeded
        else:
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                existing = {}
                cursor[part] = existing
            cursor = cast(Payload, existing)
        node = child if isinstance(child, BaseModel) else None
    cursor[parts[-1]] = value.value if isinstance(value, Enum) else value
    return patch
