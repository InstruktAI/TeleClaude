"""Display-ready configuration editor projection owned by the configuration context."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import UnionType
from typing import Any, Literal, NotRequired, TypedDict, Union, get_args, get_origin

from pydantic.fields import FieldInfo

from teleclaude.closed_model import MASKED_INPUT, ClosedModel, field_is_sensitive, mask_sensitive_values
from teleclaude.config._chiptunes import ChiptunesConfig
from teleclaude.config._defaults import DEFAULT_CONFIG
from teleclaude.config._environment import read_environment_file
from teleclaude.config._models import (
    BackupConfig,
    ComputerConfig,
    DaemonConfig,
    DiscordConfig,
    EmailConfig,
    RedisConfig,
    STTConfig,
    TelegramConfig,
    TTSConfig,
    WhatsAppConfig,
    tts_service_model,
)
from teleclaude.config._summarizer import SummarizerConfig
from teleclaude.config.effective_view import environment_references
from teleclaude.config.identity_schema import PersonEntry
from teleclaude.config.machine_environment import machine_runtime_environment_snapshot
from teleclaude.config.operation_answers import (
    EditorFieldAnswer,
    EditorInputKind,
    EditorValueState,
    EnvironmentReferenceRow,
)
from teleclaude.config.person_secrets import PersonMcpSecretStatus, person_secret_store_revision
from teleclaude.config.resource_contract import SubjectView
from teleclaude.config.revision import view_revision
from teleclaude.config.schema import PersonConfig
from teleclaude.config.surface import resolve_schema_scope
from teleclaude.config.tiers import Scope, Tier, effective_tier, pydantic_field_tier, renders_in_tui
from teleclaude.config.validation import required_field_names
from teleclaude.config_subjects import ConfigEnvironment, ConfigSubjectKind
from teleclaude.core.session_start_messages import SESSION_START_MESSAGES

_SECTION_LABELS: dict[str, str] = {
    "computer": "Computer",
    "daemon": "Daemon",
    "redis": "Redis",
    "chiptunes": "Chiptunes",
    "telegram": "Telegram",
    "discord": "Discord",
    "whatsapp": "WhatsApp",
    "backup": "Providers",
    "email": "Email",
    "summarizer": "Summarizer",
    "stt": "STT",
    "tts": "TTS",
}
_MACHINE_MODELS: dict[str, type[ClosedModel]] = {
    "computer": ComputerConfig,
    "daemon": DaemonConfig,
    "redis": RedisConfig,
    "chiptunes": ChiptunesConfig,
    "telegram": TelegramConfig,
    "discord": DiscordConfig,
    "whatsapp": WhatsAppConfig,
    "backup": BackupConfig,
    "email": EmailConfig,
    "summarizer": SummarizerConfig,
    "stt": STTConfig,
    "tts": TTSConfig,
}
_MAPPING_TYPE = dict
_LIST_TYPE = list
_SERVICES_KEY = "services"
_MODEL_KEY = "model"
_PARAMS_KEY = "params"
_CLI_BIN_KEY = "cli_bin"
_INSTRUCT_KEY = "instruct"
_VOICES_KEY = "voices"
_VOICE_ID_KEY = "voice_id"
_EVENTS_KEY = "events"
_SESSION_START_KEY = "session_start"
_MESSAGES_KEY = "messages"
_ENV_FILE_NAME = ".env"
_SECRET_FIELD_PREFIX = "secrets."
_SECRET_SECTION = "Secrets"
_SECRET_STORE_UNAVAILABLE = "unavailable"
_MACHINE_ROOT = "computer"
_MACHINE_ROOT_PREFIX = "computer."
_MASTER_FLAG = "is_master"
_FIELD_PATH_SEPARATOR = "."
_SETTINGS_SECTION_NAME = "settings"
_IDENTITY_SECTION_NAME = "identity"
_OVERLAY_ROOT = "overlay"
_PERSON_SLUG_FIELD_ID = "identity.slug"
_MISSING_VALUE = object()
_EDITOR_FIELD_VALUE_STATE_KEY = "value_state"
_EDITOR_FIELD_EDITABLE_KEY = "editable"
_EDITOR_FIELD_VALUE_KEY = "value"
_TTS_ROOT = "tts"
_IDENTITY_PATH = ("identity",)
_IDENTITY_SECTION_LABEL = "Global Identity"
_OVERLAY_SECTION_LABEL = "Overlay Settings"
_LABEL_UNDERSCORE = "_"
_LABEL_SPACE = " "
_EMPTY_TEXT = ""
_DYNAMIC_INPUT_KINDS: dict[type[object], EditorInputKind] = {
    bool: EditorInputKind.BOOLEAN,
    int: EditorInputKind.INTEGER,
    float: EditorInputKind.NUMBER,
    str: EditorInputKind.STRING,
}


class _ReferenceRevision(TypedDict):
    value: str | None
    has_value: bool


class _EditorRevisionPayload(TypedDict):
    subject: str
    references: dict[str, _ReferenceRevision]
    personal_secret_store: NotRequired[str]


def current_machine_environment() -> dict[str, str]:
    """Return the effective shell-over-file machine environment without changing process state."""
    return machine_runtime_environment_snapshot()


def editor_revision(
    view: SubjectView,
    *,
    machine_environment: Mapping[str, str] | None = None,
    environment_overrides: Mapping[ConfigEnvironment, Mapping[str, str]] | None = None,
    personal_secret_digest: str | None = None,
) -> str:
    """Hash the subject revision and the effective values of referenced editor fields."""
    references = environment_references(view, machine_environment=machine_environment)
    environments: dict[ConfigEnvironment, Mapping[str, str]] = {}
    overrides = environment_overrides or {}
    if any(row.environment is ConfigEnvironment.MACHINE for row in references):
        if ConfigEnvironment.MACHINE in overrides:
            environments[ConfigEnvironment.MACHINE] = overrides[ConfigEnvironment.MACHINE]
        else:
            environments[ConfigEnvironment.MACHINE] = (
                machine_environment if machine_environment is not None else current_machine_environment()
            )
    if any(row.environment is ConfigEnvironment.GLOBAL for row in references):
        path = view.sources[0].with_name(_ENV_FILE_NAME)
        environments[ConfigEnvironment.GLOBAL] = (
            overrides[ConfigEnvironment.GLOBAL]
            if ConfigEnvironment.GLOBAL in overrides
            else read_environment_file(path)
        )
    if any(row.environment is ConfigEnvironment.PERSON for row in references):
        path = view.sources[1].with_name(_ENV_FILE_NAME)
        environments[ConfigEnvironment.PERSON] = (
            overrides[ConfigEnvironment.PERSON]
            if ConfigEnvironment.PERSON in overrides
            else read_environment_file(path, owner_only=True)
        )
    effective: dict[str, _ReferenceRevision] = {
        row.path: _ReferenceRevision(
            value=environments.get(row.environment, {}).get(row.variable),
            has_value=row.has_value,
        )
        for row in references
    }
    secret_store_revision: str | None = None
    if view.ref.kind is ConfigSubjectKind.PERSON and view.ref.instance is not None:
        try:
            secret_store_revision = (
                personal_secret_digest
                if personal_secret_digest is not None
                else person_secret_store_revision(view.ref.instance)
            )
        except (OSError, ValueError):
            secret_store_revision = _SECRET_STORE_UNAVAILABLE
    revisions: _EditorRevisionPayload = _EditorRevisionPayload(subject=view.revision, references=effective)
    if secret_store_revision is not None:
        revisions = _EditorRevisionPayload(
            subject=view.revision,
            references=effective,
            personal_secret_store=secret_store_revision,
        )
    return view_revision(revisions)


def person_secret_editor_fields(statuses: list[PersonMcpSecretStatus]) -> list[EditorFieldAnswer]:
    """Project the existing registry-derived personal secret inventory as write-only editor fields."""
    return [
        EditorFieldAnswer(
            identity=f"{_SECRET_FIELD_PREFIX}{status.name}",
            label=status.name,
            value=MASKED_INPUT if status.is_set else None,
            input_kind=EditorInputKind.STRING,
            value_state=EditorValueState.MASKED if status.is_set else EditorValueState.DEFAULT,
            section=_SECRET_SECTION,
            editable=True,
            sensitive=True,
            requiring_services=list(status.requiring_servers),
        )
        for status in statuses
    ]


def editor_fields(
    kind: ConfigSubjectKind,
    sections: Mapping[str, object],
    *,
    source_sections: Mapping[str, object] | None = None,
    references: list[EnvironmentReferenceRow] | None = None,
) -> list[EditorFieldAnswer]:
    """Project schema-declared editable leaves and supplied effective values for a subject."""
    if kind is ConfigSubjectKind.COMPUTER:
        return _machine_fields(sections, source_sections or {}, references or [])
    if kind is ConfigSubjectKind.PERSON:
        return _person_fields(sections, source_sections or {}, references or [])
    return []


def _machine_fields(
    sections: Mapping[str, object],
    source_sections: Mapping[str, object],
    references: list[EnvironmentReferenceRow],
) -> list[EditorFieldAnswer]:
    fields: list[EditorFieldAnswer] = []
    defaults = DEFAULT_CONFIG
    effective_document = sections.get(_MACHINE_ROOT)
    computer = effective_document.get(_MACHINE_ROOT) if isinstance(effective_document, Mapping) else None
    is_master = isinstance(computer, Mapping) and bool(computer.get(_MASTER_FLAG, False))
    for root, model in _MACHINE_MODELS.items():
        default = defaults.get(root, {})
        stored = effective_document.get(root, {}) if isinstance(effective_document, Mapping) else {}
        merged = _merge(default, stored)
        if not isinstance(merged, Mapping):
            continue
        masked = mask_sensitive_values(model, merged)
        if not isinstance(masked, Mapping):
            continue
        projected = _walk_model(model, masked, (root,), _SECTION_LABELS[root], root)
        source_document = source_sections.get(_MACHINE_ROOT)
        stored = source_document.get(root) if isinstance(source_document, Mapping) else None
        projected = _set_value_states(
            projected,
            stored,
            references,
            root_prefix=root,
            reference_prefix=_MACHINE_ROOT,
        )
        projected = _tts_applicability(merged, projected) if root == _TTS_ROOT else projected
        fields.extend(field for field in projected if is_master or resolve_schema_scope(field.identity) is Scope.LOCAL)
    return fields


def _person_fields(
    sections: Mapping[str, object],
    source_sections: Mapping[str, object],
    references: list[EnvironmentReferenceRow],
) -> list[EditorFieldAnswer]:
    fields: list[EditorFieldAnswer] = []
    identity = sections.get(_IDENTITY_SECTION_NAME)
    if isinstance(identity, Mapping):
        identity_fields = _walk_model_from_mapping(
            identity, _IDENTITY_PATH, _IDENTITY_SECTION_LABEL, _IDENTITY_SECTION_NAME
        )
        identity_fields = [
            field.model_copy(update={_EDITOR_FIELD_EDITABLE_KEY: False})
            if field.identity == _PERSON_SLUG_FIELD_ID
            else field
            for field in identity_fields
        ]
        fields.extend(
            _set_value_states(
                identity_fields,
                source_sections.get(_IDENTITY_SECTION_NAME),
                references,
                root_prefix=_IDENTITY_SECTION_NAME,
            )
        )
    settings = sections.get(_SETTINGS_SECTION_NAME)
    if isinstance(settings, Mapping):
        overlay_fields = _walk_model(
            PersonConfig, settings, (_OVERLAY_ROOT,), _OVERLAY_SECTION_LABEL, _SETTINGS_SECTION_NAME
        )
        fields.extend(
            _set_value_states(
                overlay_fields,
                source_sections.get(_SETTINGS_SECTION_NAME),
                references,
                root_prefix=_OVERLAY_ROOT,
                reference_prefix=_SETTINGS_SECTION_NAME,
            )
        )
    return fields


def _set_value_states(
    fields: list[EditorFieldAnswer],
    stored: object,
    references: list[EnvironmentReferenceRow],
    *,
    root_prefix: str,
    reference_prefix: str | None = None,
) -> list[EditorFieldAnswer]:
    stored_mapping = stored if isinstance(stored, Mapping) else {}
    return [
        field.model_copy(
            update={
                _EDITOR_FIELD_VALUE_STATE_KEY: _field_value_state(
                    field,
                    _value_at(stored_mapping, tuple(field.identity.split(_FIELD_PATH_SEPARATOR)[1:])),
                    references,
                    root_prefix,
                    reference_prefix,
                )
            }
        )
        for field in fields
    ]


def _field_value_state(
    field: EditorFieldAnswer,
    stored_value: object,
    references: list[EnvironmentReferenceRow],
    root_prefix: str,
    reference_prefix: str | None,
) -> EditorValueState:
    path = field.identity
    if root_prefix == _OVERLAY_ROOT and reference_prefix is not None:
        path = f"{reference_prefix}{path.removeprefix(_OVERLAY_ROOT + _FIELD_PATH_SEPARATOR)}"
    elif reference_prefix is not None:
        path = f"{reference_prefix}{_FIELD_PATH_SEPARATOR}{path}"
    reference = next((row for row in references if row.path == path), None)
    if reference is not None and not reference.has_value:
        return EditorValueState.UNRESOLVED
    if field.sensitive and field.value == MASKED_INPUT:
        return EditorValueState.MASKED
    if stored_value is _MISSING_VALUE:
        return EditorValueState.DEFAULT
    return EditorValueState.CONFIGURED


def _value_at(document: Mapping[str, object], path: tuple[str, ...]) -> object:
    current: object = document
    for segment in path:
        if isinstance(current, Mapping):
            if segment not in current:
                return _MISSING_VALUE
            current = current[segment]
        elif isinstance(current, list) and segment.isdecimal():
            index = int(segment)
            if index >= len(current):
                return _MISSING_VALUE
            current = current[index]
        else:
            return _MISSING_VALUE
    return current


def _walk_model(
    model: type[ClosedModel], data: Mapping[str, object], prefix: tuple[str, ...], section: str, root: str
) -> list[EditorFieldAnswer]:
    fields: list[EditorFieldAnswer] = []
    required = required_field_names(root)
    for name, info in model.model_fields.items():
        path = (*prefix, name)
        tier = effective_tier(pydantic_field_tier(info), Tier.TUI)
        if not renders_in_tui(tier):
            continue
        value = data.get(name, _default_value(info))
        nested = _nested_model(info.annotation)
        if nested is not None:
            nested_data = value if isinstance(value, Mapping) else {}
            fields.extend(_walk_model(nested, nested_data, path, section, root))
            continue
        if model is TTSConfig and name == _SERVICES_KEY and isinstance(value, Mapping):
            for key, item in value.items():
                if isinstance(item, Mapping):
                    service_model = tts_service_model(str(key))
                    fields.extend(_walk_model(service_model, item, (*path, str(key)), section, root))
            continue
        if name == _PARAMS_KEY and isinstance(value, Mapping):
            fields.extend(_walk_dynamic_parameter_values(value, path, section))
            continue
        member = _container_model(info.annotation)
        if member is not None and isinstance(value, Mapping):
            for key, item in value.items():
                if isinstance(item, Mapping):
                    fields.extend(_walk_model(member, item, (*path, str(key)), section, root))
            continue
        if member is not None and isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    fields.extend(_walk_model(member, item, (*path, str(index)), section, root))
            continue
        fields.append(_field(path, info, value, section, name in required))
    return fields


def _walk_dynamic_parameter_values(
    values: Mapping[object, object], prefix: tuple[str, ...], section: str
) -> list[EditorFieldAnswer]:
    fields: list[EditorFieldAnswer] = []
    for key, value in values.items():
        path = (*prefix, str(key))
        if isinstance(value, Mapping):
            fields.extend(_walk_dynamic_parameter_values(value, path, section))
        elif isinstance(value, list) and any(isinstance(item, Mapping) for item in value):
            for index, item in enumerate(value):
                item_path = (*path, str(index))
                if isinstance(item, Mapping):
                    fields.extend(_walk_dynamic_parameter_values(item, item_path, section))
                else:
                    fields.append(_dynamic_parameter_field(item_path, item, section))
        else:
            fields.append(_dynamic_parameter_field(path, value, section))
    return fields


def _dynamic_parameter_field(path: tuple[str, ...], value: object, section: str) -> EditorFieldAnswer:
    if isinstance(value, list):
        kind = (
            EditorInputKind.STRING_LIST if all(isinstance(item, str) for item in value) else EditorInputKind.VALUE_LIST
        )
    else:
        kind = _DYNAMIC_INPUT_KINDS.get(type(value), EditorInputKind.STRING)
    return EditorFieldAnswer(
        identity=_FIELD_PATH_SEPARATOR.join(path),
        label=path[-1].replace(_LABEL_UNDERSCORE, _LABEL_SPACE).title(),
        value=value,
        input_kind=kind,
        section=section,
    )


def _walk_model_from_mapping(
    data: Mapping[str, object], prefix: tuple[str, ...], section: str, root: str
) -> list[EditorFieldAnswer]:
    return _walk_model(PersonEntry, data, prefix, section, root)


def _field(path: tuple[str, ...], info: FieldInfo, value: object, section: str, required: bool) -> EditorFieldAnswer:
    annotation = info.annotation
    kind, choices = _input_kind(annotation)
    sensitive = field_is_sensitive(info)
    safe_value = MASKED_INPUT if sensitive and value is not None else value
    return EditorFieldAnswer(
        identity=_FIELD_PATH_SEPARATOR.join(path),
        label=path[-1].replace(_LABEL_UNDERSCORE, _LABEL_SPACE).title(),
        value=safe_value,
        input_kind=kind,
        choices=choices,
        description=info.description or _EMPTY_TEXT,
        section=section,
        required=required,
        editable=True,
        sensitive=sensitive,
    )


def _input_kind(annotation: Any) -> tuple[EditorInputKind, list[str]]:
    options = get_args(annotation) if get_origin(annotation) in (Union, UnionType) else (annotation,)
    real = next((item for item in options if item is not type(None)), str)
    origin = get_origin(real)
    if origin is Literal:
        return EditorInputKind.ENUM, [str(item) for item in get_args(real)]
    if isinstance(real, type) and issubclass(real, Enum):
        return EditorInputKind.ENUM, [str(item.value) for item in real]
    if real is bool:
        return EditorInputKind.BOOLEAN, []
    if real is int:
        return EditorInputKind.INTEGER, []
    if real is float:
        return EditorInputKind.NUMBER, []
    if origin is _LIST_TYPE or real is list:
        args = get_args(real)
        return (EditorInputKind.STRING_LIST if args and args[0] is str else EditorInputKind.VALUE_LIST), []
    if isinstance(real, type) and issubclass(real, ClosedModel):
        return EditorInputKind.JSON, []
    return EditorInputKind.STRING, []


def _nested_model(annotation: Any) -> type[ClosedModel] | None:
    options = get_args(annotation) if get_origin(annotation) in (Union, UnionType) else (annotation,)
    for option in options:
        if option is type(None) or get_origin(option) in (_MAPPING_TYPE, _LIST_TYPE):
            continue
        if isinstance(option, type) and issubclass(option, ClosedModel):
            return option
    return None


def _container_model(annotation: Any) -> type[ClosedModel] | None:
    options = get_args(annotation) if get_origin(annotation) in (Union, UnionType) else (annotation,)
    for option in options:
        if get_origin(option) not in (_MAPPING_TYPE, _LIST_TYPE):
            continue
        members = get_args(option)
        candidates = members[1:] if get_origin(option) is _MAPPING_TYPE else members[:1]
        for member in candidates:
            if isinstance(member, type) and issubclass(member, ClosedModel):
                return member
    return None


def _default_value(info: FieldInfo) -> object:
    if info.is_required():
        return None
    if info.default_factory is not None:
        return info.get_default(call_default_factory=True, validated_data={})
    if info.default is not None:
        return info.default
    return None


def _merge(default: object, supplied: object) -> object:
    if not isinstance(default, Mapping) or not isinstance(supplied, Mapping):
        return supplied if supplied is not None else default
    merged = {str(key): value for key, value in default.items()}
    for key, value in supplied.items():
        name = str(key)
        merged[name] = _merge(merged.get(name), value)
    return merged


def _tts_applicability(data: object, fields: list[EditorFieldAnswer]) -> list[EditorFieldAnswer]:
    if not isinstance(data, Mapping):
        return fields
    dropped: set[str] = set()
    services = data.get(_SERVICES_KEY)
    if isinstance(services, Mapping):
        for name, service in services.items():
            if not isinstance(service, Mapping):
                continue
            base = _FIELD_PATH_SEPARATOR.join((_TTS_ROOT, _SERVICES_KEY, str(name)))
            if not service.get(_MODEL_KEY):
                dropped.update(
                    _FIELD_PATH_SEPARATOR.join((base, key))
                    for key in (_MODEL_KEY, _PARAMS_KEY, _CLI_BIN_KEY, _INSTRUCT_KEY)
                )
            voices = service.get(_VOICES_KEY)
            if not isinstance(voices, list) or not voices:
                dropped.add(_FIELD_PATH_SEPARATOR.join((base, _VOICES_KEY)))
            elif not any(isinstance(voice, Mapping) and voice.get(_VOICE_ID_KEY) for voice in voices):
                dropped.update(
                    _FIELD_PATH_SEPARATOR.join((base, _VOICES_KEY, str(index), _VOICE_ID_KEY))
                    for index in range(len(voices))
                )
    kept = [field for field in fields if field.identity not in dropped]
    events = data.get(_EVENTS_KEY)
    session_start = events.get(_SESSION_START_KEY) if isinstance(events, Mapping) else None
    if isinstance(session_start, Mapping) and not session_start.get(_MESSAGES_KEY):
        default_messages = list(SESSION_START_MESSAGES)
        kept = [
            field.model_copy(update={_EDITOR_FIELD_VALUE_KEY: default_messages})
            if field.identity == _FIELD_PATH_SEPARATOR.join((_TTS_ROOT, _EVENTS_KEY, _SESSION_START_KEY, _MESSAGES_KEY))
            else field
            for field in kept
        ]
    return kept
