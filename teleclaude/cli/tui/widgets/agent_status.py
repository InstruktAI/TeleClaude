"""Shared agent availability rendering helpers for TUI widgets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from teleclaude.api_models import AgentAvailabilityDTO
from teleclaude.cli.tui.theme import get_agent_status_color

_STATUS_TEXT_TEMPLATE = "{agent} {indicator}"
_STATUS_DETAIL_TEMPLATE = " ({detail})"
_UNKNOWN_INDICATOR = "?"
_AVAILABLE_INDICATOR = "✔"
_DEGRADED_INDICATOR = "~"
_UNAVAILABLE_INDICATOR = "✘"


class AgentRenderStatus(StrEnum):
    """Closed presentation vocabulary for agent availability."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class AgentRenderSpec:
    """Normalized visual/render contract for one agent status item."""

    agent: str
    text: str
    color_pair_id: str
    bold: bool
    selectable: bool
    status: AgentRenderStatus
    indicator: str


def classify_agent_render_status(info: AgentAvailabilityDTO | None) -> AgentRenderStatus:
    """Classify published availability fields into one presentation state."""
    if info is None or info.available is None:
        return AgentRenderStatus.UNKNOWN
    if info.status == AgentRenderStatus.DEGRADED.value:
        return AgentRenderStatus.DEGRADED
    if info.available:
        return AgentRenderStatus.AVAILABLE
    return AgentRenderStatus.UNAVAILABLE


def is_agent_selectable(info: AgentAvailabilityDTO | None) -> bool:
    """Return True when agent can be manually selected in the TUI."""
    status = classify_agent_render_status(info)
    return status in {AgentRenderStatus.AVAILABLE, AgentRenderStatus.DEGRADED}


def build_agent_render_spec(
    agent: str,
    info: AgentAvailabilityDTO | None,
    *,
    unavailable_detail: str | None = None,
    show_unavailable_detail: bool = True,
) -> AgentRenderSpec:
    """Build shared status text + style semantics for footer and modal."""
    status = classify_agent_render_status(info)
    selectable = status in {AgentRenderStatus.AVAILABLE, AgentRenderStatus.DEGRADED}
    indicator = {
        AgentRenderStatus.UNKNOWN: _UNKNOWN_INDICATOR,
        AgentRenderStatus.AVAILABLE: _AVAILABLE_INDICATOR,
        AgentRenderStatus.DEGRADED: _DEGRADED_INDICATOR,
        AgentRenderStatus.UNAVAILABLE: _UNAVAILABLE_INDICATOR,
    }[status]
    text = _STATUS_TEXT_TEMPLATE.format(agent=agent, indicator=indicator)
    if status is AgentRenderStatus.UNAVAILABLE and show_unavailable_detail and unavailable_detail:
        text += _STATUS_DETAIL_TEMPLATE.format(detail=unavailable_detail)

    return AgentRenderSpec(
        agent=agent,
        text=text,
        color_pair_id=get_agent_status_color(agent=agent, muted=status is not AgentRenderStatus.AVAILABLE),
        bold=status is AgentRenderStatus.AVAILABLE,
        selectable=selectable,
        status=status,
        indicator=indicator,
    )
