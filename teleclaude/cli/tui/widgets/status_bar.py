"""Status bar showing agent availability and toggle indicators."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.theme import get_agent_style
from teleclaude.cli.tui.utils.formatters import format_countdown


class StatusBar(Widget):
    """Bottom status bar with agent availability pills and settings toggles."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        width: 100%;
        height: 1;
        background: $surface-darken-1;
    }
    """

    tts_enabled = reactive(False)
    animation_mode = reactive("periodic")
    pane_theming_mode = reactive("off")

    def __init__(
        self,
        agent_availability: dict[str, AgentAvailabilityInfo] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._agent_availability: dict[str, AgentAvailabilityInfo] = agent_availability or {}

    def update_availability(self, availability: dict[str, AgentAvailabilityInfo]) -> None:
        self._agent_availability = availability
        self.refresh()

    def _build_agent_pill(self, agent: str) -> Text:
        """Build a single agent availability pill."""
        info = self._agent_availability.get(agent)
        available = bool(info and info.available)
        degraded = bool(info and (info.status == "degraded" or (info.reason and info.reason.startswith("degraded"))))

        if degraded:
            style = get_agent_style(agent, "muted")
            return Text(f"{agent} ~", style=style)
        elif available:
            style = get_agent_style(agent, "normal")
            return Text(f"{agent} ✔", style=style)
        else:
            until = info.unavailable_until if info else None
            countdown = format_countdown(until)
            style = get_agent_style(agent, "muted")
            return Text(f"{agent} ✘({countdown})", style=style)

    def render(self) -> Text:
        line = Text()

        # Agent availability pills
        for i, agent in enumerate(("claude", "gemini", "codex")):
            if i > 0:
                line.append("  ")
            line.append_text(self._build_agent_pill(agent))

        # Right-aligned toggles
        toggles = Text()

        # Pane theming indicator
        level = {"off": 0, "highlight": 1, "highlight2": 2, "agent": 3, "agent_plus": 4}.get(self.pane_theming_mode, 0)
        for i in range(4):
            toggles.append("◼" if i < level else "◻", style="dim" if i >= level else "")
        toggles.append("  ")

        # TTS indicator
        tts_icon = "🔊" if self.tts_enabled else "🔇"
        toggles.append(tts_icon, style="bold" if self.tts_enabled else "dim")
        toggles.append("  ")

        # Animation indicator
        anim_icons = {"off": "🚫", "periodic": "✨", "party": "🎉"}
        anim_icon = anim_icons.get(self.animation_mode, "✨")
        toggles.append(anim_icon, style="" if self.animation_mode != "off" else "dim")

        # Combine with spacing
        line.append("  │  ")
        line.append_text(toggles)

        return line

    def watch_tts_enabled(self, _value: bool) -> None:
        self.refresh()

    def watch_animation_mode(self, _value: str) -> None:
        self.refresh()

    def watch_pane_theming_mode(self, _value: str) -> None:
        self.refresh()
