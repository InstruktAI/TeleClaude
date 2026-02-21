"""Session display row with expand/collapse, agent colors, activity indicators."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.models import SessionInfo
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import (
    CONNECTOR_COLOR,
    get_selection_fg_hex,
    resolve_preview_bg_hex,
    resolve_selection_bg_hex,
    resolve_style,
)
from teleclaude.cli.tui.utils.formatters import format_time, truncate_text

_DETAIL_TEXT_LIMIT = 70


class SessionRow(TelecMixin, Widget):
    """Multi-line expandable session row for the sessions tree.

    Collapsed: `[N] ▶ agent/mode "Title"`
    Expanded: adds detail lines with depth-based │ connector, then ├/└ bottom.
    Badge [N] is always at the same left position; the │ pipe indents by depth.
    """

    class Pressed(Message):
        """Posted when a session row is clicked."""

        def __init__(self, session_row: SessionRow) -> None:
            super().__init__()
            self.session_row = session_row

    DEFAULT_CSS = """
    SessionRow {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    """

    collapsed = reactive(True, layout=True)
    is_sticky = reactive(False)
    is_preview = reactive(False)
    highlight_type = reactive("")  # "" | "input" | "output"
    active_tool = reactive("", layout=True)
    last_output_summary = reactive("", layout=True)
    skip_bottom_connector = reactive(False)
    is_last_child = reactive(False)

    def __init__(
        self,
        session: SessionInfo,
        display_index: str = "",
        depth: int = 0,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.session = session
        self.display_index = display_index
        self.depth = depth

    @property
    def session_id(self) -> str:
        return self.session.session_id

    @property
    def agent(self) -> str:
        return self.session.active_agent or "claude"

    @property
    def mode(self) -> str:
        return self.session.thinking_mode or "?"

    @property
    def status(self) -> str:
        return self.session.status or "idle"

    @property
    def _is_headless(self) -> bool:
        return self.status.startswith("headless") or not self.session.tmux_session_name

    @property
    def _child_indent(self) -> str:
        """Leading indent before the badge — constant for all depths."""
        return " "

    @property
    def _connector_col(self) -> int:
        """Column for tree │ and └ connectors (depth-based, independent of badge indent).

        depth=2 → 2, depth=3 → 3, depth=4 → 5
        """
        raw = max(0, self.depth - 2) * 2
        return (raw if raw > 0 else 1) + 1

    def _tier(self, tier: str) -> str:
        """Resolve color tier, shifting one level down for headless sessions."""
        if not self._is_headless:
            return tier
        _shift = {"highlight": "normal", "normal": "muted", "muted": "subtle", "subtle": "subtle"}
        return _shift.get(tier, tier)

    def _get_row_style(self, *, selected: bool = False, previewed: bool = False) -> Style:
        """Determine the style for the title line based on selection state.

        Matches old TUI behavior:
        - Selected: inverted — dark text on agent normal-color background, bold
        - Previewed: inverted — dark text on agent muted-color background, bold
        - Activity highlight (input/output): agent highlight color, bold
        - Normal: agent-colored text on default background
        - Headless: agent muted text on default background
        """
        if selected:
            return Style(
                color=get_selection_fg_hex(),
                bgcolor=resolve_selection_bg_hex(self.agent),
                bold=True,
            )
        if previewed:
            return Style(
                color=get_selection_fg_hex(),
                bgcolor=resolve_preview_bg_hex(self.agent),
                bold=True,
            )
        if self.collapsed and (self.highlight_type in ("input", "output") or self.active_tool):
            return resolve_style(self.agent, self._tier("highlight"))
        return resolve_style(self.agent, self._tier("normal"))

    def _build_title_line(self, *, selected: bool = False, previewed: bool = False) -> Text:
        """Build the header: `[N] ▶ agent/mode "Title"` matching old TUI format."""
        line = Text()
        indent = self._child_indent
        if indent:
            line.append(indent)

        style = self._get_row_style(selected=selected, previewed=previewed)

        # Badge: sticky → reverse. Otherwise → tier-shifted normal.
        # Never inherits selection/preview background.
        if self.is_sticky:
            badge_style = Style(reverse=True, bold=selected)
        else:
            badge_style = resolve_style(self.agent, self._tier("normal"))
        line.append(f"[{self.display_index}]", style=badge_style)

        # Space between badge and chevron inherits the row style (shows highlight)
        line.append(" ", style=style)

        # Collapse indicator
        collapse_char = "▶" if self.collapsed else "▼"
        line.append(f"{collapse_char} ", style=style)

        # Agent/mode
        line.append(f"{self.agent}/{self.mode}", style=style)

        # Subdir (slug only) — always highlighted regardless of activity state
        subdir = getattr(self.session, "subdir", None)
        if subdir:
            slug = subdir.removeprefix("trees/")
            line.append(f" {slug}", style=resolve_style(self.agent, self._tier("normal")))

        # Title in quotes
        title = self.session.title or "(untitled)"
        line.append(f'  "{title}"', style=style)

        return line

    def _build_detail_lines(self) -> list[Text]:
        """Build expanded detail lines with │ tree connectors."""
        lines: list[Text] = []
        connector_pad = " " * self._connector_col
        detail_pad = " "
        connector_style = Style(color=CONNECTOR_COLOR)

        base_style = resolve_style(self.agent, self._tier("normal"))
        highlight_style = resolve_style(self.agent, self._tier("highlight"))
        id_style = base_style

        has_input_highlight = self.highlight_type == "input"
        has_output_highlight = self.highlight_type == "output"
        has_tool_activity = bool(self.active_tool)
        input_style = highlight_style if has_input_highlight else base_style
        output_style = highlight_style if (has_output_highlight or has_tool_activity) else base_style

        # Line 2: │   [HH:MM:SS] session_id / native_session_id
        activity_time = format_time(self.session.last_activity)
        sid = self.session.session_id
        native_id = getattr(self.session, "native_session_id", None) or "-"
        line2 = Text()
        line2.append(connector_pad)
        line2.append("│", style=connector_style)
        line2.append(f"{detail_pad}[{activity_time}] {sid} / {native_id}", style=id_style)
        lines.append(line2)

        # Line 3: │   [HH:MM:SS]  in: <last input>
        last_input = (self.session.last_input or "").strip()
        last_input_at = getattr(self.session, "last_input_at", None)
        if last_input:
            input_text = last_input.replace("\n", " ")[:_DETAIL_TEXT_LIMIT]
            input_time = format_time(last_input_at)
            line3 = Text()
            line3.append(connector_pad)
            line3.append("│", style=connector_style)
            line3.append(f"{detail_pad}[{input_time}]  in: {input_text}", style=input_style)
            lines.append(line3)

        # Line 4: │   [HH:MM:SS] out: <content>
        # Whole row uses output_style color. Tool activity text is italic.
        if self.active_tool:
            activity_time_str = format_time(self.session.last_activity)
            italic_style = Style(color=output_style.color, bold=output_style.bold, italic=True)
            line4 = Text()
            line4.append(connector_pad)
            line4.append("│", style=connector_style)
            line4.append(f"{detail_pad}[{activity_time_str}] out: ", style=output_style)
            line4.append(truncate_text(self.active_tool, _DETAIL_TEXT_LIMIT), style=italic_style)
            lines.append(line4)
        elif self.last_output_summary:
            summary_at = getattr(self.session, "last_output_summary_at", None) or self.session.last_activity
            output_time = format_time(summary_at)
            output_text = self.last_output_summary.replace("\n", " ")[:_DETAIL_TEXT_LIMIT]
            line4 = Text()
            line4.append(connector_pad)
            line4.append("│", style=connector_style)
            line4.append(f"{detail_pad}[{output_time}] out: {output_text}", style=output_style)
            lines.append(line4)
        elif has_input_highlight or has_output_highlight:
            activity_time_str = format_time(self.session.last_activity)
            line4 = Text()
            line4.append(connector_pad)
            line4.append("│", style=connector_style)
            line4.append(f"{detail_pad}[{activity_time_str}] out: ...", style=output_style)
            lines.append(line4)

        return lines

    def _build_connector_bottom(self) -> Text:
        """Build the bottom connector line.

        Uses └ (corner) for last child in a subtree, ├ (tee) otherwise.
        """
        connector_pad = " " * self._connector_col
        connector_style = Style(color=CONNECTOR_COLOR)
        run_len = max(self.size.width - self._connector_col - 1, 20)
        char = "\u2514" if self.is_last_child else "\u251c"
        line = Text()
        line.append(connector_pad)
        line.append(char, style=connector_style)
        line.append("-" * run_len, style=connector_style)
        return line

    def render(self) -> Text:
        is_selected = self.has_class("selected")
        is_previewed = self.is_preview

        result = self._build_title_line(selected=is_selected, previewed=is_previewed)
        if not self.collapsed:
            for detail in self._build_detail_lines():
                result.append("\n")
                result.append_text(detail)
            # Bottom connector (skipped for last session before GroupSeparator)
            if not self.skip_bottom_connector:
                result.append("\n")
                result.append_text(self._build_connector_bottom())
        return result

    def on_click(self, event: Click) -> None:
        """Post Pressed message when clicked."""
        event.stop()
        self.post_message(self.Pressed(self))

    def update_session(self, session: SessionInfo) -> None:
        """Update the underlying session data and trigger re-render."""
        self.session = session
        self.refresh(layout=True)

    def watch_collapsed(self, _value: bool) -> None:
        self.refresh()

    def watch_is_sticky(self, _value: bool) -> None:
        self.set_class(self.is_sticky, "sticky")
        self.refresh()

    def watch_is_preview(self, _value: bool) -> None:
        self.set_class(self.is_preview, "preview")
        self.refresh()

    def watch_highlight_type(self, _value: str) -> None:
        self.refresh()

    def watch_active_tool(self, _value: str) -> None:
        self.refresh()

    def watch_last_output_summary(self, _value: str) -> None:
        self.refresh()
