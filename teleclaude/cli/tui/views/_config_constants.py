"""Shared constants, data classes, and utility functions for the config view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich.style import Style

from teleclaude.cli.config_handlers import EnvVarStatus
from teleclaude.cli.tui.config_components.guidance import get_guidance_for_env
from teleclaude.cli.tui.theme import CONNECTOR_COLOR, get_neutral_color

_SUBTABS = ("adapters", "people", "notifications", "environment")
_PERSON_EDITABLE_FIELDS = ("email", "role", "username")
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
class NotificationProjection:
    """Summary of notification setup state."""

    configured: bool
    total_people: int
    people_with_subscriptions: int
    total_subscriptions: int
    next_action: str


@dataclass(frozen=True)
class GuidedStep:
    """Deterministic guided mode step."""

    subtab: str
    title: str
    adapter_tab: str | None = None


_GUIDED_STEPS: tuple[GuidedStep, ...] = (
    GuidedStep(subtab="adapters", adapter_tab="telegram", title="Configure Telegram"),
    GuidedStep(subtab="adapters", adapter_tab="discord", title="Configure Discord"),
    GuidedStep(subtab="adapters", adapter_tab="ai_keys", title="Configure AI + Voice"),
    GuidedStep(subtab="adapters", adapter_tab="whatsapp", title="Configure WhatsApp"),
    GuidedStep(subtab="people", title="Review People"),
    GuidedStep(subtab="notifications", title="Review Notifications"),
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
    notifications_configured: bool,
    environment_configured: bool,
) -> tuple[int, int]:
    """Return configured/total summary across adapter and core sections."""
    configured = sum(1 for section in adapter_sections if section.status == "configured")
    configured += int(has_people)
    configured += int(notifications_configured)
    configured += int(environment_configured)
    total = len(adapter_sections) + 3
    return configured, total


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
    "NotificationProjection",
    "_normal_style",
    "classify_adapter_status",
    "completion_summary",
    "get_guidance_for_env",
    "project_adapter_sections",
]
