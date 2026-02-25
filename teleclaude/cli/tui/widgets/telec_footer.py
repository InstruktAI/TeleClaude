"""Unified three-row footer (context hints, global hints, controls)."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.events import Click
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.messages import SettingsChanged, StateChanged
from teleclaude.cli.tui.theme import get_agent_color, get_agent_style
from teleclaude.cli.tui.utils.formatters import format_countdown


class TelecFooter(Widget):
    """Bottom footer with three rows:

    1) Context-aware bindings
    2) Global bindings
    3) Agent availability + controls
    """

    DEFAULT_CSS = """
    TelecFooter {
        width: 100%;
        height: 3;
    }
    """

    tts_enabled = reactive(False)
    animation_mode = reactive("periodic")
    pane_theming_mode = reactive("off")
    persistence_key = "status_bar"

    def __init__(
        self,
        agent_availability: dict[str, AgentAvailabilityInfo] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._agent_availability: dict[str, AgentAvailabilityInfo] = agent_availability or {}
        self._toggle_start_x: int = 0
        self._tts_start_x: int = 0
        self._tts_end_x: int = 0
        self._anim_start_x: int = 0
        self._agent_regions: list[tuple[int, int, str]] = []

    def on_mount(self) -> None:
        self.screen.bindings_updated_signal.subscribe(self, self._on_bindings_changed)

    def on_unmount(self) -> None:
        self.screen.bindings_updated_signal.unsubscribe(self)

    def _on_bindings_changed(self, _screen: object) -> None:
        if self.app.app_focus:
            self.refresh()

    def update_availability(self, availability: dict[str, AgentAvailabilityInfo]) -> None:
        self._agent_availability = availability
        self.refresh()

    def _collect_rows(self) -> tuple[list[tuple[Binding, bool, str]], list[tuple[Binding, bool, str]]]:
        active_bindings = self.screen.active_bindings

        context_row: list[tuple[Binding, bool, str]] = []
        global_row: list[tuple[Binding, bool, str]] = []
        seen_context_actions: set[str] = set()
        seen_global_actions: set[str] = set()

        for node, binding, enabled, tooltip in active_bindings.values():
            if not binding.show:
                continue

            is_global = node is self.app
            seen = seen_global_actions if is_global else seen_context_actions
            if binding.action in seen:
                continue
            seen.add(binding.action)

            item = (binding, enabled, tooltip)
            if is_global:
                global_row.append(item)
            else:
                context_row.append(item)

        return context_row, global_row

    def _format_binding_item(self, binding: Binding, *, enabled: bool, tooltip: str, dim: bool) -> Text:
        key = self.app.get_key_display(binding)
        label = tooltip or binding.description

        text = Text()
        key_style = Style(color="white", bold=True, dim=(not enabled) or dim)
        label_style = Style(dim=(not enabled) or dim)
        text.append(str(key), style=key_style)
        if label:
            text.append(" ")
            text.append(label, style=label_style)
        return text

    def _render_hints_line(self, items: list[tuple[Binding, bool, str]], *, dim: bool, empty_label: str) -> Text:
        line = Text()
        if items:
            for idx, (binding, enabled, tooltip) in enumerate(items):
                if idx:
                    line.append("  ")
                line.append_text(self._format_binding_item(binding, enabled=enabled, tooltip=tooltip, dim=dim))
        else:
            line.append(empty_label, style=Style(dim=True))
        return line

    def _build_agent_pill(self, agent: str) -> Text:
        info = self._agent_availability.get(agent)
        available = bool(info and info.available)
        degraded = bool(info and (info.status == "degraded" or (info.reason and info.reason.startswith("degraded"))))

        if degraded:
            style = get_agent_style(agent, "muted")
            return Text(f"{agent} ~", style=style)
        if available:
            style = get_agent_style(agent, "normal")
            return Text(f"{agent} ✔", style=style)

        until = info.unavailable_until if info else None
        countdown = format_countdown(until)
        style = get_agent_style(agent, "muted")
        return Text(f"{agent} ✘({countdown})", style=style)

    def _build_pane_theming_cells(self) -> list[tuple[str, Style]]:
        level = {"off": 0, "highlight": 1, "highlight2": 2, "agent": 3, "agent_plus": 4}.get(self.pane_theming_mode, 0)

        outline_color = get_agent_color("codex", "muted")
        outline_style = Style(color=outline_color, dim=True)
        highlight_style = get_agent_style("codex", "highlight")
        agent_styles = [
            get_agent_style("claude", "normal"),
            get_agent_style("gemini", "normal"),
            get_agent_style("codex", "normal"),
        ]
        accent_style = get_agent_style("codex", "highlight")

        if level == 0:
            fill_styles: list[Style] = []
        elif level == 1:
            fill_styles = [highlight_style]
        elif level == 2:
            fill_styles = [highlight_style, highlight_style]
        elif level == 3:
            fill_styles = list(agent_styles)
        else:
            fill_styles = [*agent_styles, accent_style]

        cells: list[tuple[str, Style]] = []
        for box_idx in range(4):
            if box_idx < len(fill_styles):
                cells.append(("\u25fc", fill_styles[box_idx]))
            else:
                cells.append(("\u25fb", outline_style))
        return cells

    def _render_controls_line(self) -> Text:
        line = Text()
        self._agent_regions = []

        for i, agent in enumerate(("claude", "gemini", "codex")):
            if i > 0:
                line.append("  ")
            start_x = line.cell_len
            line.append_text(self._build_agent_pill(agent))
            end_x = line.cell_len
            self._agent_regions.append((start_x, end_x, agent))

        toggles = Text()
        for cell_char, cell_style in self._build_pane_theming_cells():
            toggles.append(cell_char, style=cell_style)
        toggles.append("  ")

        tts_start = toggles.cell_len
        tts_icon = "\U0001f50a" if self.tts_enabled else "\U0001f507"
        toggles.append(tts_icon, style="bold" if self.tts_enabled else "dim")
        tts_end = toggles.cell_len
        toggles.append("  ")

        anim_start = toggles.cell_len
        anim_icons = {"off": "\U0001f6ab", "periodic": "\u2728", "party": "\U0001f389"}
        anim_icon = anim_icons.get(self.animation_mode, "\u2728")
        toggles.append(anim_icon, style="" if self.animation_mode != "off" else "dim")

        left_len = line.cell_len
        right_len = toggles.cell_len
        gap = max(2, self.size.width - left_len - right_len)
        line.append(" " * gap)

        offset = left_len + gap
        self._toggle_start_x = offset
        self._tts_start_x = offset + tts_start
        self._tts_end_x = offset + tts_end
        self._anim_start_x = offset + anim_start

        line.append_text(toggles)
        return line

    def render(self) -> Text:
        context_row, global_row = self._collect_rows()
        line1 = self._render_hints_line(context_row, dim=False, empty_label="No context actions")
        line2 = self._render_hints_line(global_row, dim=True, empty_label="No global actions")
        line3 = self._render_controls_line()
        return Text.assemble(line1, "\n", line2, "\n", line3)

    def on_click(self, event: Click) -> None:
        if event.y != 2:
            return

        x = event.x
        for start_x, end_x, agent in self._agent_regions:
            if start_x <= x < end_x:
                self.post_message(SettingsChanged("agent_status", {"agent": agent}))
                return

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
        if self.is_mounted:
            self.post_message(StateChanged())

    def watch_pane_theming_mode(self, _value: str) -> None:
        self.refresh()
        if self.is_mounted:
            self.post_message(StateChanged())

    def get_persisted_state(self) -> dict[str, object]:  # guard: loose-dict - widget state payload
        return {
            "animation_mode": self.animation_mode,
            "pane_theming_mode": self.pane_theming_mode,
        }

    def load_persisted_state(self, data: dict[str, object]) -> None:  # guard: loose-dict - widget state payload
        animation_mode = data.get("animation_mode")
        if isinstance(animation_mode, str) and animation_mode in {"off", "periodic", "party"}:
            self.animation_mode = animation_mode

        pane_theming_mode = data.get("pane_theming_mode")
        if isinstance(pane_theming_mode, str) and pane_theming_mode:
            from teleclaude.cli.tui.theme import normalize_pane_theming_mode

            try:
                self.pane_theming_mode = normalize_pane_theming_mode(pane_theming_mode)
            except ValueError:
                pass
