"""Shared constants, data classes, and utility functions for the config view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Union, get_args, get_origin

from rich.style import Style

from teleclaude.cli.config_handlers import EnvVarStatus
from teleclaude.cli.tui.config_components.guidance import get_guidance_for_env
from teleclaude.cli.tui.theme import CONNECTOR_COLOR, get_neutral_color
from teleclaude.config.schema import PersonEntry

_SUBTABS = ("adapters", "people", "environment")
_PERSON_EDITABLE_FIELDS = ("name", "email", "role", "username", "preferences", "expertise")
_VALID_ROLES = ("admin", "member", "contributor", "newcomer")
_ADAPTER_TABS = ("telegram", "discord", "ai_keys", "whatsapp")
_ADAPTER_LABELS = {
    "telegram": "Telegram",
    "discord": "Discord",
    "ai_keys": "AI + Voice",
    "whatsapp": "WhatsApp",
}
_ADAPTER_ENV_KEYS = {
    "telegram": ("telegram",),
    "discord": ("discord",),
    "ai_keys": ("ai", "voice"),
    "whatsapp": ("whatsapp",),
}

# Styles


def _normal_style() -> Style:
    """Normal text style — adapts to dark/light mode."""
    return Style(color=get_neutral_color("highlight"))


_DIM = Style(color="#727578")
_OK = Style(color="#5faf5f")
_FAIL = Style(color="#d75f5f")
_WARN = Style(color="#d7af5f")
_INFO = Style(color="#87afd7")
_SEP = Style(color=CONNECTOR_COLOR)
_TAB_ACTIVE = Style(bold=True, reverse=True)
_TAB_INACTIVE = Style(color="#808080")

AdapterStatus = Literal["configured", "partial", "unconfigured"]


@dataclass(frozen=True)
class AdapterSectionProjection:
    """Computed adapter section state for rendering and guided flow."""

    key: str
    label: str
    env_statuses: list[EnvVarStatus]
    status: AdapterStatus
    configured_count: int
    total_count: int


@dataclass(frozen=True)
class GuidedStep:
    """Deterministic guided mode step."""

    subtab: str
    title: str
    adapter_tab: str | None = None


_GUIDED_STEPS: tuple[GuidedStep, ...] = (
    GuidedStep(subtab="people", title="Admin Setup"),
    GuidedStep(subtab="adapters", adapter_tab="telegram", title="Configure Telegram"),
    GuidedStep(subtab="adapters", adapter_tab="discord", title="Configure Discord"),
    GuidedStep(subtab="adapters", adapter_tab="ai_keys", title="Configure AI + Voice"),
    GuidedStep(subtab="adapters", adapter_tab="whatsapp", title="Configure WhatsApp"),
    GuidedStep(subtab="environment", title="Review Environment"),
)


def classify_adapter_status(env_statuses: list[EnvVarStatus]) -> AdapterStatus:
    """Classify adapter setup status from env var state."""
    if not env_statuses:
        return "unconfigured"
    configured_count = sum(1 for status in env_statuses if status.is_set)
    if configured_count == 0:
        return "unconfigured"
    if configured_count == len(env_statuses):
        return "configured"
    return "partial"


def project_adapter_sections(env_data: list[EnvVarStatus]) -> list[AdapterSectionProjection]:
    """Build adapter section projections for the configured tab set."""
    sections: list[AdapterSectionProjection] = []
    for key in _ADAPTER_TABS:
        adapter_keys = _ADAPTER_ENV_KEYS[key]
        statuses = [status for status in env_data if status.info.adapter in adapter_keys]
        configured_count = sum(1 for status in statuses if status.is_set)
        sections.append(
            AdapterSectionProjection(
                key=key,
                label=_ADAPTER_LABELS.get(key, key),
                env_statuses=statuses,
                status=classify_adapter_status(statuses),
                configured_count=configured_count,
                total_count=len(statuses),
            )
        )
    return sections


def completion_summary(
    adapter_sections: list[AdapterSectionProjection],
    *,
    has_people: bool,
    environment_configured: bool,
) -> tuple[int, int]:
    """Return configured/total summary across adapter and core sections."""
    configured = sum(1 for section in adapter_sections if section.status == "configured")
    configured += int(has_people)
    configured += int(environment_configured)
    total = len(adapter_sections) + 2
    return configured, total


def get_allowed_values_for_field(field_name: str) -> list[str] | None:
    """Extract Literal allowed values from PersonEntry schema or Union annotations."""

    def unpack_union(t: Any) -> list[Any]:
        if get_origin(t) in (Union, getattr(Union, "_UnionGenericAlias", None), getattr(Union, "UnionType", None)):
            return list(get_args(t))
        return [t]

    if ":" in field_name:
        parent, _ = field_name.split(":", 1)
        if parent in PersonEntry.model_fields:
            ann = PersonEntry.model_fields[parent].annotation
            # Unpack Optionals/Unions to find dict type
            dict_types = [t for t in unpack_union(ann) if get_origin(t) is dict or t is dict]
            if dict_types:
                dict_ann = dict_types[0]
                args = get_args(dict_ann)
                if len(args) == 2:
                    val_type = args[1]
                    for option in unpack_union(val_type):
                        if get_origin(option) is Literal:
                            return list(get_args(option))
    else:
        if field_name in PersonEntry.model_fields:
            ann = PersonEntry.model_fields[field_name].annotation
            for option in unpack_union(ann):
                if get_origin(option) is Literal:
                    return list(get_args(option))
    return None


__all__ = [
    "_ADAPTER_ENV_KEYS",
    "_ADAPTER_LABELS",
    "_ADAPTER_TABS",
    "_DIM",
    "_FAIL",
    "_GUIDED_STEPS",
    "_INFO",
    "_OK",
    "_PERSON_EDITABLE_FIELDS",
    "_SEP",
    "_SUBTABS",
    "_TAB_ACTIVE",
    "_TAB_INACTIVE",
    "_VALID_ROLES",
    "_WARN",
    "AdapterSectionProjection",
    "AdapterStatus",
    "GuidedStep",
    "_normal_style",
    "classify_adapter_status",
    "completion_summary",
    "get_allowed_values_for_field",
    "get_guidance_for_env",
    "project_adapter_sections",
]
