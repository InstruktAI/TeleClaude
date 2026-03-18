"""Status bar showing agent availability and toggle indicators."""

from __future__ import annotations

from rich.text import Text
from textual.events import Click
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.messages import SettingsChanged, StateChanged
from teleclaude.cli.tui.widgets._status_controls import (
    build_agent_pill,
    build_pane_theming_cells,
    cycle_animation_mode,
    get_persisted_state,
    load_persisted_state,
)
from teleclaude.core.agents import get_known_agents


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
    animation_mode = reactive("off")
    pane_theming_mode = reactive("off")
    persistence_key = "status_bar"

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
        self._anim_start_x: int = 0
        # Track agent pill positions: (start_x, end_x, agent_name)
        self._agent_regions: list[tuple[int, int, str]] = []

    def update_availability(self, availability: dict[str, AgentAvailabilityInfo]) -> None:
        """Replace cached agent availability data and refresh the widget."""
        self._agent_availability = availability
        self.refresh()

    def _build_agent_pill(self, agent: str) -> Text:
        """Build a single agent availability pill."""
        return build_agent_pill(agent, self._agent_availability.get(agent))

    def _build_pane_theming_cells(self) -> list[tuple[str, object]]:
        """Build pane theming indicator cells with agent-colored squares.

        Matches old curses TUI footer._format_pane_mode_cells:
        - Level 0 (off):         4 outline squares (codex muted + dim)
        - Level 1 (highlight):   1 codex-highlight filled, 3 outline
        - Level 2 (highlight2):  2 codex-highlight filled, 2 outline
        - Level 3 (agent):       claude/gemini/codex normal colors, 1 outline
        - Level 4 (agent_plus):  claude/gemini/codex normal + codex highlight
        """
        return build_pane_theming_cells(self.pane_theming_mode)

    def _build_toggle_line(self) -> tuple[Text, int, int, int]:
        """Build the right-aligned toggle cluster and its click offsets."""
        toggles = Text()
        for cell_char, cell_style in self._build_pane_theming_cells():
            toggles.append(cell_char, style=cell_style)
        toggles.append("  ")

        tts_start = toggles.cell_len
        tts_icon = "\U0001f50a" if self.tts_enabled else "\U0001f507"
        toggles.append(tts_icon, style="bold" if self.tts_enabled else "dim")
        toggles.append("  ")

        anim_start = toggles.cell_len
        anim_icon = {"off": "\U0001f6ab", "periodic": "\u2728", "party": "\U0001f389"}.get(
            self.animation_mode,
            "\u2728",
        )
        toggles.append(anim_icon, style="" if self.animation_mode != "off" else "dim")
        return toggles, 0, tts_start, anim_start

    def render(self) -> Text:
        """Render agent pills on the left and control toggles on the right."""
        line = Text()
        self._agent_regions = []

        # Left: agent availability pills
        for i, agent in enumerate(get_known_agents()):
            if i > 0:
                line.append("  ")
            start_x = line.cell_len
            line.append_text(self._build_agent_pill(agent))
            end_x = line.cell_len
            self._agent_regions.append((start_x, end_x, agent))

        toggles, toggle_start, tts_start, anim_start = self._build_toggle_line()

        # Right-align toggles
        left_len = line.cell_len
        right_len = toggles.cell_len
        gap = max(2, self.size.width - left_len - right_len)
        line.append(" " * gap)

        # Record toggle positions (absolute x within the widget)
        offset = left_len + gap
        self._toggle_start_x = offset + toggle_start
        self._tts_start_x = offset + tts_start
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
            self.post_message(SettingsChanged("animation_mode", cycle_animation_mode(self.animation_mode)))
        elif x >= self._tts_start_x:
            self.post_message(SettingsChanged("tts_enabled", not self.tts_enabled))
        elif x >= self._toggle_start_x:
            self.post_message(SettingsChanged("pane_theming_mode", "cycle"))

    def watch_tts_enabled(self, _value: bool) -> None:
        """Refresh when the TTS toggle changes."""
        self.refresh()

    def watch_animation_mode(self, _value: str) -> None:
        """Refresh and persist state when the animation mode changes."""
        self.refresh()
        if self.is_mounted:
            self.post_message(StateChanged())

    def watch_pane_theming_mode(self, _value: str) -> None:
        """Refresh and persist state when pane theming changes."""
        self.refresh()
        if self.is_mounted:
            self.post_message(StateChanged())

    def get_persisted_state(self) -> dict[str, object]:  # guard: loose-dict - widget state payload
        """Return the persisted state payload for footer toggles."""
        return get_persisted_state(self.animation_mode, self.pane_theming_mode)

    def load_persisted_state(self, data: dict[str, object]) -> None:  # guard: loose-dict - widget state payload
        """Restore persisted footer toggle state."""
        load_persisted_state(self, data)
