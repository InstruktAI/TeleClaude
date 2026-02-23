"""Status bar showing agent availability and toggle indicators."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.events import Click
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.messages import SettingsChanged
from teleclaude.cli.tui.theme import get_agent_color, get_agent_style
from teleclaude.cli.tui.utils.formatters import format_countdown


class StatusBar(TelecMixin, Widget):
    """Bottom status bar with agent availability pills and settings toggles.

    Toggles are clickable:
    - Pane theming squares: cycle through 5 levels (off/highlight/highlight2/agent/agent_plus)
    - TTS icon: toggle on/off
    - Animation icon: cycle off/periodic/party
    """

    DEFAULT_CSS = """
    StatusBar {
        width: 100%;
        height: 1;
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
        # Track toggle positions for click detection (set during render)
        self._toggle_start_x: int = 0
        self._tts_start_x: int = 0
        self._tts_end_x: int = 0
        self._anim_start_x: int = 0
        # Track agent pill positions: (start_x, end_x, agent_name)
        self._agent_regions: list[tuple[int, int, str]] = []

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

    def _build_pane_theming_cells(self) -> list[tuple[str, Style]]:
        """Build pane theming indicator cells with agent-colored squares.

        Matches old curses TUI footer._format_pane_mode_cells:
        - Level 0 (off):         4 outline squares (codex muted + dim)
        - Level 1 (highlight):   1 codex-highlight filled, 3 outline
        - Level 2 (highlight2):  2 codex-highlight filled, 2 outline
        - Level 3 (agent):       claude/gemini/codex normal colors, 1 outline
        - Level 4 (agent_plus):  claude/gemini/codex normal + codex highlight
        """
        level = {"off": 0, "highlight": 1, "highlight2": 2, "agent": 3, "agent_plus": 4}.get(self.pane_theming_mode, 0)

        # Outline style: codex muted + dim (for unfilled squares)
        outline_color = get_agent_color("codex", "muted")
        outline_style = Style(color=outline_color, dim=True)

        # Highlight style for levels 1-2: codex highlight color
        highlight_style = get_agent_style("codex", "highlight")

        # Agent normal colors for levels 3-4 (one per agent)
        agent_styles = [
            get_agent_style("claude", "normal"),
            get_agent_style("gemini", "normal"),
            get_agent_style("codex", "normal"),
        ]

        # Accent for the 4th square in level 4: codex highlight
        accent_style = get_agent_style("codex", "highlight")

        # Build fill styles based on level
        if level == 0:
            fill_styles: list[Style] = []
        elif level == 1:
            fill_styles = [highlight_style]
        elif level == 2:
            fill_styles = [highlight_style, highlight_style]
        elif level == 3:
            fill_styles = list(agent_styles)
        else:  # level 4
            fill_styles = [*agent_styles, accent_style]

        cells: list[tuple[str, Style]] = []
        for box_idx in range(4):
            if box_idx < len(fill_styles):
                cells.append(("\u25fc", fill_styles[box_idx]))
            else:
                cells.append(("\u25fb", outline_style))
        return cells

    def render(self) -> Text:
        line = Text()
        self._agent_regions = []

        # Left: agent availability pills
        for i, agent in enumerate(("claude", "gemini", "codex")):
            if i > 0:
                line.append("  ")
            start_x = line.cell_len
            line.append_text(self._build_agent_pill(agent))
            end_x = line.cell_len
            self._agent_regions.append((start_x, end_x, agent))

        # Right: toggles (pane theming, TTS, animation)
        toggles = Text()

        # Pane theming indicator (4 colored squares)
        for cell_char, cell_style in self._build_pane_theming_cells():
            toggles.append(cell_char, style=cell_style)
        toggles.append("  ")

        # TTS indicator
        tts_start = toggles.cell_len
        tts_icon = "\U0001f50a" if self.tts_enabled else "\U0001f507"
        toggles.append(tts_icon, style="bold" if self.tts_enabled else "dim")
        tts_end = toggles.cell_len
        toggles.append("  ")

        # Animation indicator
        anim_start = toggles.cell_len
        anim_icons = {"off": "\U0001f6ab", "periodic": "\u2728", "party": "\U0001f389"}
        anim_icon = anim_icons.get(self.animation_mode, "\u2728")
        toggles.append(anim_icon, style="" if self.animation_mode != "off" else "dim")

        # Right-align toggles
        left_len = line.cell_len
        right_len = toggles.cell_len
        gap = max(2, self.size.width - left_len - right_len)
        line.append(" " * gap)

        # Record toggle positions (absolute x within the widget)
        offset = left_len + gap
        self._toggle_start_x = offset
        self._tts_start_x = offset + tts_start
        self._tts_end_x = offset + tts_end
        self._anim_start_x = offset + anim_start

        line.append_text(toggles)
        return line

    def on_click(self, event: Click) -> None:
        """Handle clicks on agent pills and toggle regions."""
        x = event.x

        # Check agent pill clicks first
        for start_x, end_x, agent in self._agent_regions:
            if start_x <= x < end_x:
                self.post_message(SettingsChanged("agent_status", {"agent": agent}))
                return

        # Check toggle clicks
        if x >= self._anim_start_x:
            cycle = ["off", "periodic", "party"]
            idx = cycle.index(self.animation_mode) if self.animation_mode in cycle else 0
            new_mode = cycle[(idx + 1) % len(cycle)]
            self.post_message(SettingsChanged("animation_mode", new_mode))
        elif x >= self._tts_start_x:
            self.post_message(SettingsChanged("tts_enabled", not self.tts_enabled))
        elif x >= self._toggle_start_x:
            self.post_message(SettingsChanged("pane_theming_mode", "cycle"))

    def watch_tts_enabled(self, _value: bool) -> None:
        self.refresh()

    def watch_animation_mode(self, _value: str) -> None:
        self.refresh()

    def watch_pane_theming_mode(self, _value: str) -> None:
        self.refresh()
