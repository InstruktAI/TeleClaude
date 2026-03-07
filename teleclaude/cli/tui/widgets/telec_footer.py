"""Unified three-row footer (context hints, global hints, controls)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.events import Click
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.messages import SettingsChanged, StateChanged
from teleclaude.cli.tui.theme import get_agent_color, get_agent_style, get_neutral_color
from teleclaude.cli.tui.utils.formatters import format_countdown


class FooterActionButton(Static, can_focus=False):
    """Single-line icon button for the packed footer layout."""

    icon = reactive("")

    class Pressed(Message):
        def __init__(self, button: FooterActionButton) -> None:
            self.button = button
            super().__init__()

    DEFAULT_CSS = """
    FooterActionButton {
        min-width: 0;
        width: 4;
        height: 1;
        margin: 0 1 0 0;
        background: transparent;
        color: $text;
        content-align: center middle;
        pointer: pointer;
    }

    FooterActionButton:hover {
        background: $surface;
    }

    FooterActionButton:disabled {
        color: auto 50%;
        background: transparent;
        text-style: dim;
    }
    """

    def __init__(self, icon: str, **kwargs: object) -> None:
        super().__init__("", markup=False, **kwargs)
        self.icon = icon

    def on_mount(self) -> None:
        self.update(self._render_icon())

    def watch_icon(self, _value: str) -> None:
        if self.is_mounted:
            self.update(self._render_icon())

    def watch_disabled(self, disabled: bool) -> None:
        self.set_class(disabled, "-disabled")
        if self.is_mounted:
            self.update(self._render_icon())

    def _render_icon(self) -> Text:
        return Text(self.icon, style=Style(bold=not self.disabled, dim=self.disabled))

    def on_click(self, event: Click) -> None:
        if self.disabled:
            return
        event.stop()
        self.post_message(self.Pressed(self))


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

    #footer-context-row,
    #footer-global-row {
        height: 1;
        width: 100%;
        content-align: left middle;
    }

    #footer-controls-row {
        height: 1;
        width: 100%;
    }

    #footer-agents,
    #footer-actions {
        height: 1;
        width: auto;
    }

    #footer-controls-spacer {
        width: 1fr;
        height: 1;
    }

    .footer-token {
        width: auto;
        min-width: 0;
        height: 1;
        margin: 0 1 0 0;
        background: transparent;
    }

    .footer-token:hover {
        background: transparent;
    }

    .footer-agent-token {
        margin: 0 2 0 0;
    }

    .footer-agent-token.-last-agent,
    .footer-token.-last-token {
        margin: 0;
    }

    .footer-action-button {
        margin: 0 1 0 0;
    }

    .footer-action-button.-last-action {
        margin: 0;
    }

    #footer-prev,
    #footer-play,
    #footer-next,
    #footer-fav {
        width: 4;
    }
    """

    tts_enabled = reactive(False)
    chiptunes_enabled = reactive(False)
    chiptunes_playing = reactive(False)
    chiptunes_track = reactive("")
    chiptunes_sid_path = reactive("")
    chiptunes_favorited = reactive(False)
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

    def compose(self) -> ComposeResult:
        yield Static(id="footer-context-row")
        yield Static(id="footer-global-row")
        with Horizontal(id="footer-controls-row"):
            with Horizontal(id="footer-agents"):
                for idx, agent in enumerate(("claude", "gemini", "codex")):
                    classes = "footer-token footer-agent-token"
                    if idx == 2:
                        classes += " -last-agent"
                    yield Static("", id=f"footer-agent-{agent}", classes=classes)
            yield Static("", id="footer-controls-spacer")
            with Horizontal(id="footer-actions"):
                yield Static("", id="footer-pane-toggle", classes="footer-token")
                yield Static("", id="footer-tts-toggle", classes="footer-token")
                yield FooterActionButton("\u23ee\ufe0f", id="footer-prev", classes="footer-action-button")
                yield FooterActionButton("\u25b6\ufe0f", id="footer-play", classes="footer-action-button")
                yield FooterActionButton("\u23ed\ufe0f", id="footer-next", classes="footer-action-button")
                yield FooterActionButton("\u2b50", id="footer-fav", classes="footer-action-button -last-action")
                yield Static("", id="footer-anim-toggle", classes="footer-token -last-token")

    def on_mount(self) -> None:
        self.screen.bindings_updated_signal.subscribe(self, self._on_bindings_changed)
        self._refresh_hint_rows()
        self._refresh_controls()

    def on_unmount(self) -> None:
        self.screen.bindings_updated_signal.unsubscribe(self)

    def _on_bindings_changed(self, _screen: object) -> None:
        if self.app.app_focus:
            self._refresh_hint_rows()

    def update_availability(self, availability: dict[str, AgentAvailabilityInfo]) -> None:
        self._agent_availability = availability
        self._refresh_controls()

    def _collect_rows(self) -> tuple[list[tuple[Binding, bool, str]], list[tuple[Binding, bool, str]]]:
        active_bindings = self.screen.active_bindings

        context_row: list[tuple[Binding, bool, str]] = []
        global_row: list[tuple[Binding, bool, str]] = []
        seen_context_actions: set[str] = set()
        seen_global_actions: set[str] = set()

        for node, binding, enabled, tooltip in active_bindings.values():
            if not binding.show:
                continue

            is_global = node is self.app or (binding.group and binding.group.description == "global")
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

    def _format_binding_item(self, binding: Binding, *, enabled: bool, tooltip: str) -> Text:
        key = self.app.get_key_display(binding)
        label = tooltip or binding.description

        text = Text()
        key_style = (
            Style(bold=True, dim=True) if not enabled else Style(bold=True, color=get_neutral_color("highlight"))
        )
        label_style = Style(dim=True)
        text.append(str(key), style=key_style)
        if label:
            text.append(" ")
            text.append(label, style=label_style)
        return text

    def _render_hints_line(self, items: list[tuple[Binding, bool, str]], *, empty_label: str) -> Text:
        line = Text()
        if items:
            for idx, (binding, enabled, tooltip) in enumerate(items):
                if idx:
                    line.append("  ")
                line.append_text(self._format_binding_item(binding, enabled=enabled, tooltip=tooltip))
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

    def _refresh_hint_rows(self) -> None:
        if not self.is_mounted:
            return
        context_row, global_row = self._collect_rows()
        self.query_one("#footer-context-row", Static).update(
            self._render_hints_line(context_row, empty_label="No context actions")
        )
        self.query_one("#footer-global-row", Static).update(
            self._render_hints_line(global_row, empty_label="No global actions")
        )

    def _set_token(self, selector: str, label: Text | str) -> None:
        self.query_one(selector, Static).update(label)

    def _refresh_controls(self) -> None:
        if not self.is_mounted:
            return

        for agent in ("claude", "gemini", "codex"):
            self._set_token(f"#footer-agent-{agent}", self._build_agent_pill(agent))

        pane_toggle = Text()
        for cell_char, cell_style in self._build_pane_theming_cells():
            pane_toggle.append(cell_char, style=cell_style)
        self._set_token("#footer-pane-toggle", pane_toggle)

        tts_icon = Text("\U0001f50a" if self.tts_enabled else "\U0001f507", style="bold" if self.tts_enabled else "dim")
        self._set_token("#footer-tts-toggle", tts_icon)

        self._refresh_transport_buttons()

        anim_icons = {"off": "\U0001f6ab", "periodic": "\u2728", "party": "\U0001f389"}
        anim_icon = Text(
            anim_icons.get(self.animation_mode, "\u2728"),
            style="" if self.animation_mode != "off" else "dim",
        )
        self._set_token("#footer-anim-toggle", anim_icon)

    def _refresh_transport_buttons(self) -> None:
        prev_button = self.query_one("#footer-prev", FooterActionButton)
        play_button = self.query_one("#footer-play", FooterActionButton)
        next_button = self.query_one("#footer-next", FooterActionButton)
        fav_button = self.query_one("#footer-fav", FooterActionButton)

        prev_button.icon = "\u23ee\ufe0f"
        play_button.icon = "\u23f8\ufe0f" if (self.chiptunes_enabled and self.chiptunes_playing) else "\u25b6\ufe0f"
        next_button.icon = "\u23ed\ufe0f"
        fav_button.icon = "\u2705" if (self.chiptunes_enabled and self.chiptunes_favorited) else "\u2b50"

        prev_button.disabled = not self.chiptunes_enabled
        next_button.disabled = not self.chiptunes_enabled
        fav_button.disabled = not self.chiptunes_enabled
        # Play can enable chiptunes from the stopped state.
        play_button.disabled = False

    def on_click(self, event: Click) -> None:
        widget = event.widget
        if widget is None or widget is self:
            return
        if isinstance(widget, FooterActionButton):
            return
        widget_id = widget.id
        if widget_id is None:
            return
        if widget_id.startswith("footer-agent-"):
            self.post_message(SettingsChanged("agent_status", {"agent": widget_id.removeprefix("footer-agent-")}))
            return
        if widget_id == "footer-pane-toggle":
            self.post_message(SettingsChanged("pane_theming_mode", "cycle"))
            return
        if widget_id == "footer-tts-toggle":
            self.post_message(SettingsChanged("tts_enabled", not self.tts_enabled))
            return
        if not self.chiptunes_enabled and widget_id in {"footer-prev", "footer-play", "footer-next", "footer-fav"}:
            return
        if widget_id == "footer-prev":
            self.post_message(SettingsChanged("chiptunes_prev", None))
            return
        if widget_id == "footer-play":
            self.post_message(SettingsChanged("chiptunes_play_pause", None))
            return
        if widget_id == "footer-next":
            self.post_message(SettingsChanged("chiptunes_next", None))
            return
        if widget_id == "footer-fav":
            self.post_message(SettingsChanged("chiptunes_favorite", None))
            return
        if widget_id == "footer-anim-toggle":
            cycle = ["off", "periodic", "party"]
            idx = cycle.index(self.animation_mode) if self.animation_mode in cycle else 0
            new_mode = cycle[(idx + 1) % len(cycle)]
            self.post_message(SettingsChanged("animation_mode", new_mode))

    def on_footer_action_button_pressed(self, event: FooterActionButton.Pressed) -> None:
        button_id = event.button.id
        if button_id == "footer-prev":
            self.post_message(SettingsChanged("chiptunes_prev", None))
            return
        if button_id == "footer-play":
            self.post_message(SettingsChanged("chiptunes_play_pause", None))
            return
        if button_id == "footer-next":
            self.post_message(SettingsChanged("chiptunes_next", None))
            return
        if button_id == "footer-fav":
            self.post_message(SettingsChanged("chiptunes_favorite", None))

    def watch_tts_enabled(self, _value: bool) -> None:
        self._refresh_controls()

    def watch_chiptunes_enabled(self, _value: bool) -> None:
        self._refresh_controls()

    def watch_chiptunes_playing(self, _value: bool) -> None:
        self._refresh_controls()

    def watch_chiptunes_favorited(self, _value: bool) -> None:
        self._refresh_controls()

    def watch_animation_mode(self, _value: str) -> None:
        self._refresh_controls()
        if self.is_mounted:
            self.post_message(StateChanged())

    def watch_pane_theming_mode(self, _value: str) -> None:
        self._refresh_controls()
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
