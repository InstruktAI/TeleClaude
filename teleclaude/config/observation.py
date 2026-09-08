"""Sanitized projections emitted at the machine-config load boundary."""

from __future__ import annotations

from enum import StrEnum
from typing import TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.config.validation import is_section_available, missing_required_fields

logger = get_logger(__name__)

AGENT_CONFIG_VALIDATION_EVENT = "agent_runtime.agent_config_validation"


class AgentConfigValidationStage(StrEnum):
    """Closed lifecycle stage for one agents-block validation pass."""

    STARTED = "started"


class AgentConfigValidationOutcome(StrEnum):
    """Closed terminal outcome for one agents-block validation pass."""

    ACCEPTED = "accepted"
    REFUSED = "refused"


class AgentConfigRefusalReason(StrEnum):
    """Closed refusal reason for a rejected agents block."""

    MISSING_DEFAULT = "missing_default"
    UNKNOWN_DEFAULT = "unknown_default"
    UNKNOWN_AGENT_KEY = "unknown_agent_key"
    ALL_DISABLED = "all_disabled"
    DEFAULT_DISABLED = "default_disabled"


def log_agent_config_validation(
    *,
    load_id: str,
    digest: str,
    stage: AgentConfigValidationStage | None = None,
    outcome: AgentConfigValidationOutcome | None = None,
    reason: AgentConfigRefusalReason | None = None,
    default_agent: str | None = None,
    enabled_count: int | None = None,
    registry_count: int | None = None,
) -> None:
    """Emit one closed agent-config-validation observation record.

    Carries no config body, credential, or account content — only the
    correlation id, the registry digest it was validated against, and the
    closed stage/outcome/reason tokens the observation map requires.
    """
    fields: dict[str, object] = {}  # guard: loose-dict - structured logger kwargs
    fields["load_id"] = load_id
    fields["registry_digest"] = digest
    if stage is not None:
        fields["stage"] = stage.value
    if outcome is not None:
        fields["outcome"] = outcome.value
    if reason is not None:
        fields["reason"] = reason.value
    if default_agent is not None:
        fields["default_agent"] = default_agent
    if enabled_count is not None:
        fields["enabled_count"] = enabled_count
    if registry_count is not None:
        fields["registry_count"] = registry_count
    logger.info(AGENT_CONFIG_VALIDATION_EVENT, **fields)


SOURCE_ABSENT = "absent"
SOURCE_LITERAL = "literal"
SOURCE_PLACEHOLDER = "placeholder"
AVAILABILITY_DISABLED = "disabled"
AVAILABILITY_AVAILABLE = "available"
AVAILABILITY_UNAVAILABLE = "unavailable"
MISSING_REQUIRED_FIELD = "missing_required_field"
CONFIG_SOURCE_PATHS = (
    ("telegram", "bot_token"),
    ("telegram", "alert_username"),
    ("telegram", "alert_chat_id"),
    ("discord", "token"),
    ("discord", "guild_id"),
    ("whatsapp", "phone_number_id"),
    ("whatsapp", "access_token"),
    ("whatsapp", "business_number"),
    ("email", "smtp_username"),
    ("email", "smtp_key"),
    ("email", "email_from"),
)


class SectionAvailability(TypedDict):
    """Sanitized availability state for one credential-bearing section."""

    enabled: bool
    availability: str
    reason: str | None


def _source_kind(value: object) -> str:
    """Classify a raw scalar without recording its value."""
    if value is None:
        return SOURCE_ABSENT
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return SOURCE_PLACEHOLDER
    return SOURCE_LITERAL


def _nested_value(raw: object, path: tuple[str, ...]) -> object | None:
    """Read one raw config path without assigning a fallback value."""
    current = raw
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def credential_field_sources(raw: object) -> dict[str, str]:
    """Describe credential ingress by path and source kind, never by value."""
    return {".".join(path): _source_kind(_nested_value(raw, path)) for path in CONFIG_SOURCE_PATHS}


def credential_section_availability(resolved: object) -> dict[str, SectionAvailability]:
    """Project enabled and required-field availability from the typed aggregate."""
    projection: dict[str, SectionAvailability] = {}
    for section_name in ("telegram", "discord", "whatsapp", "email"):
        section = getattr(resolved, section_name)
        enabled = section.enabled
        missing = missing_required_fields(section_name, section)
        if not enabled:
            availability = AVAILABILITY_DISABLED
        elif is_section_available(section_name, section):
            availability = AVAILABILITY_AVAILABLE
        else:
            availability = AVAILABILITY_UNAVAILABLE
        projection[section_name] = {
            "enabled": enabled,
            "availability": availability,
            "reason": MISSING_REQUIRED_FIELD if missing else None,
        }
    return projection
