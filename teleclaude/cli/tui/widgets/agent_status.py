"""Shared agent availability rendering helpers for TUI widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.theme import AGENT_COLORS

AgentStatus = Literal["available", "degraded", "unavailable"]


@dataclass(frozen=True)
class AgentRenderSpec:
    """Normalized visual/render contract for one agent status item."""

    agent: str
    text: str
    color_pair_id: int
    bold: bool
    selectable: bool
    status: AgentStatus


def is_agent_degraded(info: AgentAvailabilityInfo | None) -> bool:
    """Return True when the agent is marked degraded."""
    if not info:
        return False
    if info.status == "degraded":
        return True
    return isinstance(info.reason, str) and info.reason.startswith("degraded")


def is_agent_selectable(info: AgentAvailabilityInfo | None) -> bool:
    """Return True when agent can be manually selected in the TUI."""
    return bool(info and info.available is True)


def build_agent_render_spec(
    agent: str,
    info: AgentAvailabilityInfo | None,
    *,
    unavailable_detail: str | None = None,
    show_unavailable_detail: bool = True,
) -> AgentRenderSpec:
    """Build shared status text + style semantics for footer and modal."""
    selectable = is_agent_selectable(info)
    degraded = is_agent_degraded(info)
    available = selectable and not degraded

    agent_colors = AGENT_COLORS.get(agent, {"subtle": 0, "muted": 0, "normal": 0, "highlight": 0})
    color_pair_id = agent_colors["normal"] if selectable else agent_colors["muted"]

    if degraded:
        text = f"{agent} ~"
        status: AgentStatus = "degraded"
        bold = False
    elif available:
        text = f"{agent} ✔"
        status = "available"
        bold = True
    else:
        detail = unavailable_detail or "?"
        detail_suffix = f" ({detail})" if show_unavailable_detail else ""
        text = f"{agent} ✘{detail_suffix}"
        status = "unavailable"
        bold = False

    return AgentRenderSpec(
        agent=agent,
        text=text,
        color_pair_id=color_pair_id,
        bold=bold,
        selectable=selectable,
        status=status,
    )
