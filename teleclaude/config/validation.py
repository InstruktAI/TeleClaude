"""Shared schema-path applicability, availability, and requirement validation.

One source of truth for whether a schema path applies, is enabled, and has its
required values — consumed by configuration projections and downstream gates.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from teleclaude.config._environment import whole_reference_name
from teleclaude.config._schema_paths import MODEL_FIELDS_ATTRIBUTE, PATH_SEPARATOR, resolve_schema_scope
from teleclaude.config.effective_enabled import ENABLED_FIELD
from teleclaude.config.tiers import Scope, pydantic_field_governs_section


def is_unresolved_placeholder(value: object) -> bool:
    """Return True when a config value is empty or an unresolved ``${VAR}``.

    Config secrets are shipped as ``${VAR}`` references into ``.env``; an
    unresolved reference (or an empty/None value) means the field is not
    actually filled in. Treating the literal ``${VAR}`` string as a real value
    is the bug this guards against.
    """
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        return not stripped or whole_reference_name(stripped) is not None
    return False


@dataclass(frozen=True)
class _RequiredField:
    """A required typed field and its human-facing validation label."""

    label: str
    config_attr: str


class AvailabilityState(StrEnum):
    """Configuration readiness for one schema path."""

    NOT_APPLICABLE = "not_applicable"
    DISABLED = "disabled"
    INCOMPLETE = "incomplete"
    AVAILABLE = "available"


class _ConfigField(StrEnum):
    COMPUTER = "computer"
    IS_MASTER = "is_master"
    ENABLED = "enabled"
    AVAILABILITY = "availability"


_PATH_NOT_FOUND = object()


@dataclass(frozen=True)
class AvailabilityAnswer:
    """Safe availability result; missing fields are identities and never values."""

    state: AvailabilityState
    missing_fields: tuple[str, ...] = ()


def configuration_availability(config: object, path: str) -> AvailabilityAnswer:
    """Resolve applicability, enablement, and declared credential requirements for a path."""
    if not _scope_applies(config, path):
        return AvailabilityAnswer(AvailabilityState.NOT_APPLICABLE)
    section = _value_at_path(config, path)
    if section is None or not _governing_enablement_applies(config, path):
        return AvailabilityAnswer(AvailabilityState.DISABLED)
    missing = _missing_for_path(path, section, config)
    if missing:
        return AvailabilityAnswer(AvailabilityState.INCOMPLETE, tuple(missing))
    return AvailabilityAnswer(AvailabilityState.AVAILABLE)


def _scope_applies(config: object, path: str) -> bool:
    scope = resolve_schema_scope(type(config), path)
    computer = getattr(config, _ConfigField.COMPUTER.value, None)
    return scope is not Scope.MASTER or bool(getattr(computer, _ConfigField.IS_MASTER.value, False))


def _value_at_path(config: object, path: str) -> object:
    value = config
    for part in path.split(PATH_SEPARATOR):
        value = _path_value(value, part)
        if value is _PATH_NOT_FOUND or value is None:
            return None
    return value


def _read_field(value: object, name: str, default: object) -> object:
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def _governing_enablement_applies(config: object, path: str) -> bool:
    value = config
    for part in path.split(PATH_SEPARATOR):
        if not _node_enablement_applies(value):
            return False
        value = _path_value(value, part)
        if value is _PATH_NOT_FOUND or value is None:
            return False
    return _node_enablement_applies(value)


def _node_enablement_applies(value: object) -> bool:
    fields = getattr(type(value), MODEL_FIELDS_ATTRIBUTE, None)
    if not isinstance(fields, dict) or ENABLED_FIELD not in fields:
        return True
    enabled_field = fields[ENABLED_FIELD]
    if not pydantic_field_governs_section(enabled_field):
        return True
    return bool(getattr(value, ENABLED_FIELD, False))


def _path_value(value: object, part: str) -> object:
    if isinstance(value, Mapping):
        return value.get(part, _PATH_NOT_FOUND)
    if isinstance(value, list) and part.isdecimal():
        index = int(part)
        return value[index] if index < len(value) else _PATH_NOT_FOUND
    return getattr(value, part, _PATH_NOT_FOUND)


def _missing_for_path(path: str, section: object, config: object) -> list[str]:
    missing = [
        field_path
        for name in required_field_names(path)
        if (field_path := PATH_SEPARATOR.join((path, name)))
        and _scope_applies(config, field_path)
        and is_unresolved_placeholder(_read_field(section, name, None))
    ]
    for provider_path, fields in missing_enabled_service_fields(config).items():
        for name in fields:
            missing_path = PATH_SEPARATOR.join((provider_path, name))
            if _path_is_prefix(path, missing_path) and _scope_applies(config, missing_path):
                missing.append(missing_path)
    return missing


def _path_is_prefix(path: str, candidate: str) -> bool:
    return path == candidate or candidate.startswith(path + PATH_SEPARATOR)


# Per-section required fields, read only from the typed config aggregate.
_REQUIRED_FIELDS: dict[str, tuple[_RequiredField, ...]] = {
    "discord": (_RequiredField("token", "token"),),
    "telegram": (_RequiredField("bot token", "bot_token"),),
    "whatsapp": (
        _RequiredField("phone_number_id", "phone_number_id"),
        _RequiredField("access_token", "access_token"),
    ),
    "email": (
        _RequiredField("smtp_username", "smtp_username"),
        _RequiredField("smtp_key", "smtp_key"),
        _RequiredField("email_from", "email_from"),
    ),
}


def _resolve_field(cfg: object, spec: _RequiredField) -> str:
    """Read one required field from its config section."""
    raw = cfg.get(spec.config_attr) if isinstance(cfg, dict) else getattr(cfg, spec.config_attr, None)
    return "" if is_unresolved_placeholder(raw) else str(raw).strip()


def missing_required_fields(section: str, cfg: object) -> list[str]:
    """Return the required field labels that are missing/unconfigured for a section.

    ``cfg`` is either a parsed config object or a raw config-section dict. An
    empty list means fully configured; sections with no requirements always
    return an empty list.
    """
    return [spec.label for spec in _REQUIRED_FIELDS.get(section, ()) if not _resolve_field(cfg, spec)]


def validated_sections() -> frozenset[str]:
    """Config sections that carry required-field requirements (callers gate on these)."""
    return frozenset(_REQUIRED_FIELDS)


def required_field_names(section: str) -> frozenset[str]:
    """Return the validation-owned required field names for one config section."""
    return frozenset(spec.config_attr for spec in _REQUIRED_FIELDS.get(section, ()))


def missing_enabled_service_fields(config: object) -> dict[str, list[str]]:
    """Return missing typed fields for enabled optional provider services."""
    missing: dict[str, list[str]] = {}
    summarizer = getattr(config, "summarizer", None)
    local = getattr(summarizer, "local", None) if summarizer is not None else None
    if local is not None and _node_enablement_applies(local):
        local_missing = [
            field_name
            for field_name in ("base_url", "model")
            if is_unresolved_placeholder(getattr(local, field_name, None))
        ]
        if local_missing:
            missing["summarizer.local"] = local_missing

    for section_name in ("tts", "stt"):
        section = getattr(config, section_name, None)
        if section is None or not _node_enablement_applies(section):
            continue
        services = getattr(section, "services", None)
        elevenlabs = services.get("elevenlabs") if services else None
        if elevenlabs is not None and getattr(elevenlabs, "enabled", False):
            if is_unresolved_placeholder(getattr(elevenlabs, "api_key", None)):
                missing[f"{section_name}.services.elevenlabs"] = ["api_key"]

    return missing


def is_section_available(section: str, cfg: object) -> bool:
    """Boolean adapter for the configuration owner's complete path answer."""
    availability = getattr(cfg, _ConfigField.AVAILABILITY.value, None)
    answer = (
        cast(AvailabilityAnswer, availability(section))
        if callable(availability)
        else configuration_availability(cfg, section)
    )
    return answer.state is AvailabilityState.AVAILABLE
