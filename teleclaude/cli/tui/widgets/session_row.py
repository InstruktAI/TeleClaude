"""Session display row with expand/collapse, agent colors, activity indicators."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.models import SessionInfo
from teleclaude.cli.tui.theme import get_agent_color, get_agent_style
from teleclaude.cli.tui.utils.formatters import format_relative_time, shorten_path, truncate_text


class SessionRow(Widget):
    """Multi-line expandable session row for the sessions tree.

    Compact (collapsed): single line with agent badge, title, status indicator, time
    Expanded: adds detail lines (last input, last output summary, session ID)
    """

    DEFAULT_CSS = """
    SessionRow {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    SessionRow.selected {
        background: $accent-darken-2;
    }
    SessionRow.preview {
        background: $primary-darken-2;
    }
    SessionRow.sticky {
        background: $primary-darken-3;
    }
    """

    collapsed = reactive(True)
    is_sticky = reactive(False)
    is_preview = reactive(False)
    highlight_type = reactive("")  # "" | "input" | "output"
    active_tool = reactive("")
    last_output_summary = reactive("")

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
    def status(self) -> str:
        return self.session.status or "idle"

    def _status_indicator(self) -> tuple[str, str]:
        """Return (indicator_char, style) based on session status and highlights."""
        if self.highlight_type == "input":
            return ("●", "bold yellow")
        if self.highlight_type == "output":
            return ("●", f"bold {get_agent_color(self.agent, 'normal')}")
        if self.active_tool:
            return ("◐", f"{get_agent_color(self.agent, 'muted')}")
        status = self.status
        if status == "input":
            return ("▸", "yellow")
        if status in ("thinking", "output"):
            return ("◐", get_agent_color(self.agent, "normal"))
        return ("·", "dim")

    def _build_title_line(self) -> Text:
        """Build the compact single-line representation."""
        line = Text()
        indent = "  " * self.depth

        # Index
        line.append(f"{indent}{self.display_index} ", style="dim")

        # Agent badge
        agent_style = get_agent_style(self.agent, "normal")
        line.append(f"[{self.agent}]", style=agent_style)
        line.append(" ")

        # Status indicator
        indicator, indicator_style = self._status_indicator()
        line.append(indicator, style=indicator_style)
        line.append(" ")

        # Title
        title = self.session.title or "(untitled)"
        line.append(truncate_text(title, 50))

        # Sticky badge
        if self.is_sticky:
            line.append(" ◆", style="bold")

        # Time
        time_str = format_relative_time(self.session.last_activity)
        if time_str:
            line.append(f"  {time_str}", style="dim")

        return line

    def _build_detail_lines(self) -> list[Text]:
        """Build expanded detail lines."""
        lines: list[Text] = []
        indent = "  " * (self.depth + 1)
        dim = "dim"

        # Project path
        if self.session.project_path:
            path = shorten_path(self.session.project_path, 60)
            lines.append(Text(f"{indent}  {path}", style=dim))

        # Last input
        if self.session.last_input:
            inp = truncate_text(self.session.last_input, 65)
            line = Text(f"{indent}  in: ", style=dim)
            line.append(inp)
            lines.append(line)

        # Output summary or active tool
        if self.active_tool:
            line = Text(f"{indent}  ", style=dim)
            line.append(truncate_text(self.active_tool, 65), style=get_agent_color(self.agent, "muted"))
            lines.append(line)
        elif self.last_output_summary:
            summary = truncate_text(self.last_output_summary, 65)
            line = Text(f"{indent}  out: ", style=dim)
            line.append(summary, style=get_agent_color(self.agent, "muted"))
            lines.append(line)

        # Session ID (truncated)
        sid = self.session.session_id[:8]
        mode = self.session.thinking_mode or ""
        meta = f"{sid}"
        if mode:
            meta += f" [{mode}]"
        lines.append(Text(f"{indent}  {meta}", style="dim italic"))

        return lines

    def render(self) -> Text:
        result = self._build_title_line()
        if not self.collapsed:
            for detail in self._build_detail_lines():
                result.append("\n")
                result.append_text(detail)
        return result

    def update_session(self, session: SessionInfo) -> None:
        """Update the underlying session data and trigger re-render."""
        self.session = session
        self.refresh()

    def watch_collapsed(self, _value: bool) -> None:
        self.refresh()

    def watch_is_sticky(self, _value: bool) -> None:
        self.toggle_class("sticky", self.is_sticky)
        self.refresh()

    def watch_is_preview(self, _value: bool) -> None:
        self.toggle_class("preview", self.is_preview)
        self.refresh()

    def watch_highlight_type(self, _value: str) -> None:
        self.refresh()

    def watch_active_tool(self, _value: str) -> None:
        self.refresh()

    def watch_last_output_summary(self, _value: str) -> None:
        self.refresh()
