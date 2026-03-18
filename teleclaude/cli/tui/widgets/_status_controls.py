"""Shared helpers for footer and status-bar control rendering/state."""

from __future__ import annotations

from typing import Protocol

from rich.style import Style
from rich.text import Text

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.theme import get_agent_color, get_agent_style, normalize_pane_theming_mode
from teleclaude.cli.tui.utils.formatters import format_countdown

_ANIMATION_MODES = ("off", "periodic", "party")
_PANE_THEMING_LEVELS = {"off": 0, "highlight": 1, "highlight2": 2, "agent": 3, "agent_plus": 4}


class _SettingsWidget(Protocol):  # pylint: disable=too-few-public-methods
    animation_mode: str
    pane_theming_mode: str


def build_pane_theming_cells(pane_theming_mode: str) -> list[tuple[str, Style]]:
    """Build the four pane-theming indicator cells for footer widgets."""
    level = _PANE_THEMING_LEVELS.get(pane_theming_mode, 0)
    outline_style = Style(color=get_agent_color("codex", "muted"), dim=True)
    highlight_style = get_agent_style("codex", "highlight")
    agent_styles = [
        get_agent_style("claude", "normal"),
        get_agent_style("gemini", "normal"),
        get_agent_style("codex", "normal"),
    ]

    if level == 0:
        fill_styles: list[Style] = []
    elif level == 1:
        fill_styles = [highlight_style]
    elif level == 2:
        fill_styles = [highlight_style, highlight_style]
    elif level == 3:
        fill_styles = list(agent_styles)
    else:
        fill_styles = [*agent_styles, get_agent_style("codex", "highlight")]

    return [
        ("\u25fc", fill_styles[index]) if index < len(fill_styles) else ("\u25fb", outline_style) for index in range(4)
    ]


def build_agent_pill(agent: str, availability: AgentAvailabilityInfo | None) -> Text:
    """Build the standard agent availability pill used by footer widgets."""
    available = bool(availability and availability.available)
    degraded = bool(
        availability
        and (availability.status == "degraded" or (availability.reason and availability.reason.startswith("degraded")))
    )

    if degraded:
        return Text(f"{agent} ~", style=get_agent_style(agent, "muted"))
    if available:
        return Text(f"{agent} ✔", style=get_agent_style(agent, "normal"))

    until = availability.unavailable_until if availability else None
    countdown = format_countdown(until)
    return Text(f"{agent} ✘({countdown})", style=get_agent_style(agent, "muted"))


def cycle_animation_mode(animation_mode: str) -> str:
    """Advance the animation mode through the supported cycle."""
    try:
        index = _ANIMATION_MODES.index(animation_mode)
    except ValueError:
        index = 0
    return _ANIMATION_MODES[(index + 1) % len(_ANIMATION_MODES)]


def get_persisted_state(animation_mode: str, pane_theming_mode: str) -> dict[str, object]:
    """Return the persisted state payload for shared footer controls."""
    return {
        "animation_mode": animation_mode,
        "pane_theming_mode": pane_theming_mode,
    }


def load_persisted_state(widget: _SettingsWidget, data: dict[str, object]) -> None:
    """Restore persisted footer control state onto a widget instance."""
    animation_mode = data.get("animation_mode")
    if isinstance(animation_mode, str) and animation_mode in _ANIMATION_MODES:
        widget.animation_mode = animation_mode

    pane_theming_mode = data.get("pane_theming_mode")
    if isinstance(pane_theming_mode, str) and pane_theming_mode:
        try:
            widget.pane_theming_mode = normalize_pane_theming_mode(pane_theming_mode)
        except ValueError:
            pass
