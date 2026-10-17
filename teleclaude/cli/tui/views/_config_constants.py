"""Shared constants, data classes, and utility functions for the config view."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from instrukt_ai_logging import get_logger
from rich.style import Style

from teleclaude.cli.tui.theme import CONNECTOR_COLOR, get_neutral_color
from teleclaude.cli.tui.views.config_operations import EnvVarStatus

logger = get_logger(__name__)

CONFIG_TUI_OBSERVATION_EVENT = "config_tui_observation"
OUTCOME_FIELD = "outcome"


class ConfigTuiOutcome(StrEnum):
    """Closed outcome vocabulary for config-TUI observations."""

    RENDER_REQUESTED = "render_requested"
    RENDERED = "rendered"
    SAVE_REQUESTED = "save_requested"
    SAVED = "saved"
    BLOCKED = "blocked"
    FAILED = "failed"
    GUIDED_COMPLETENESS = "guided_completeness"


class ConfigTuiRowAction(StrEnum):
    """Closed row-click routing vocabulary for the Config screen."""

    PERSON_SELECT = "person_select"
    ENVIRONMENT = "env_row"
    REFLECTED_FIELD = "reflected_row"
    PERSON_FIELD = "person_reflected_row"


def observe_config_tui(outcome: ConfigTuiOutcome, **details: object) -> None:
    """Emit a sanitized config-TUI lifecycle observation."""
    logger.info(CONFIG_TUI_OBSERVATION_EVENT, **{OUTCOME_FIELD: outcome.value, **details})


class Subtab(StrEnum):
    """Config-view subtab identifiers."""

    INFRA = "Infra"
    PEOPLE = "People"
    ADAPTERS = "Adapters"
    PROVIDERS = "Providers"
    SUMMARIZER = "Summarizer"
    TTS_STT = "TTS/STT"
    ENV = "Env"


# Ordered tabs for index-based navigation (active_subtab).
_SUBTABS = tuple(Subtab)


class AdapterTab(StrEnum):
    """Adapter sub-tab identifiers."""

    TELEGRAM = "telegram"
    DISCORD = "discord"
    AI_KEYS = "ai_keys"
    WHATSAPP = "whatsapp"


# Ordered adapter tabs for index-based navigation (active_adapter_tab).
_ADAPTER_TABS = tuple(AdapterTab)
_ADAPTER_LABELS = {
    AdapterTab.TELEGRAM: "Telegram",
    AdapterTab.DISCORD: "Discord",
    AdapterTab.AI_KEYS: "AI + Voice",
    AdapterTab.WHATSAPP: "WhatsApp",
}
_ADAPTER_ENV_KEYS = {
    AdapterTab.TELEGRAM: ("telegram",),
    AdapterTab.DISCORD: ("discord",),
    AdapterTab.AI_KEYS: ("ai", "voice"),
    AdapterTab.WHATSAPP: ("whatsapp",),
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

    key: AdapterTab
    label: str
    env_statuses: list[EnvVarStatus]
    status: AdapterStatus
    configured_count: int
    total_count: int


@dataclass(frozen=True)
class GuidedStep:
    """Deterministic guided mode step."""

    subtab: Subtab
    step_label: str
    adapter_tab: str | None = None


_GUIDED_STEPS: tuple[GuidedStep, ...] = (
    GuidedStep(subtab=Subtab.INFRA, step_label="Configure Infrastructure"),
    GuidedStep(subtab=Subtab.PEOPLE, step_label="Admin Setup"),
    GuidedStep(subtab=Subtab.ADAPTERS, step_label="Configure UI Adapters"),
    GuidedStep(subtab=Subtab.PROVIDERS, step_label="Configure Providers"),
    GuidedStep(subtab=Subtab.SUMMARIZER, step_label="Configure Summarizer"),
    GuidedStep(subtab=Subtab.TTS_STT, step_label="Configure TTS/STT"),
    GuidedStep(subtab=Subtab.ENV, step_label="Review Environment"),
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


__all__ = [
    "_ADAPTER_ENV_KEYS",
    "_ADAPTER_LABELS",
    "_ADAPTER_TABS",
    "_DIM",
    "_FAIL",
    "_GUIDED_STEPS",
    "_INFO",
    "_OK",
    "_SEP",
    "_SUBTABS",
    "_TAB_ACTIVE",
    "_TAB_INACTIVE",
    "_WARN",
    "AdapterSectionProjection",
    "AdapterStatus",
    "AdapterTab",
    "GuidedStep",
    "Subtab",
    "_normal_style",
    "classify_adapter_status",
    "project_adapter_sections",
]
