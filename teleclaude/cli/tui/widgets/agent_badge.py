"""Reusable agent name badge with color."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.tui.theme import get_agent_style


class AgentBadge(Widget):
    """Small pill showing agent name with agent-specific color."""

    DEFAULT_CSS = """
    AgentBadge {
        width: auto;
        height: 1;
    }
    """

    agent = reactive("claude")

    def render(self) -> Text:
        style = get_agent_style(self.agent, "normal")
        return Text(self.agent, style=style)
