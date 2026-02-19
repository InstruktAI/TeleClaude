"""Session display row with expand/collapse, agent colors, activity indicators."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.models import SessionInfo
from teleclaude.cli.tui.theme import get_agent_color, get_agent_style
from teleclaude.cli.tui.utils.formatters import format_time, truncate_text

_DETAIL_TEXT_LIMIT = 70


class SessionRow(Widget):
    """Multi-line expandable session row for the sessions tree.

    Collapsed: `[N] ▶ agent/mode "Title"`
    Expanded: adds `[HH:MM:SS] sid / native_id`, `[HH:MM:SS]  in: ...`, `[HH:MM:SS] out: ...`
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
    def mode(self) -> str:
        return self.session.thinking_mode or "?"

    @property
    def status(self) -> str:
        return self.session.status or "idle"

    def _build_title_line(self) -> Text:
        """Build the header: `[N] ▶ agent/mode "Title"` matching old TUI format."""
        line = Text()
        indent = " " * (max(0, self.depth - 1) * 2)
        if indent:
            line.append(indent)

        # Agent style for entire row
        agent_style = get_agent_style(self.agent, "normal")
        is_headless = self.status.startswith("headless") or not self.session.tmux_session_name
        row_style = get_agent_style(self.agent, "muted") if is_headless else agent_style

        # Index badge — sticky sessions show position number
        line.append(f"[{self.display_index}]", style=row_style)
        line.append(" ")

        # Collapse indicator
        collapse_char = "▶" if self.collapsed else "▼"
        line.append(f"{collapse_char} ", style=row_style)

        # Agent/mode
        line.append(f"{self.agent}/{self.mode}", style=row_style)

        # Subdir if present
        subdir = getattr(self.session, "subdir", None)
        if subdir:
            subdir_display = subdir.removeprefix("trees/")
            line.append(f" {subdir_display}", style=row_style)

        # Title in quotes
        title = self.session.title or "(untitled)"
        line.append(f'  "{title}"', style=row_style)

        return line

    def _build_detail_lines(self) -> list[Text]:
        """Build expanded detail lines matching old TUI format."""
        lines: list[Text] = []
        detail_indent = " " * (max(0, self.depth - 1) * 2) + "    "
        agent_style = get_agent_style(self.agent, "normal")
        highlight_style = (
            get_agent_style(self.agent, "highlight") if hasattr(get_agent_style, "__call__") else agent_style
        )
        muted_style = get_agent_style(self.agent, "muted")

        has_input_highlight = self.highlight_type == "input"
        has_output_highlight = self.highlight_type == "output"
        input_style = highlight_style if has_input_highlight else agent_style
        output_style = highlight_style if has_output_highlight else agent_style

        # Line 2: [HH:MM:SS] session_id / native_session_id
        activity_time = format_time(self.session.last_activity)
        sid = self.session.session_id
        native_id = getattr(self.session, "native_session_id", None) or "-"
        line2 = Text(f"{detail_indent}[{activity_time}] {sid} / {native_id}", style=muted_style)
        lines.append(line2)

        # Line 3: [HH:MM:SS]  in: <last input>
        last_input = (self.session.last_input or "").strip()
        last_input_at = getattr(self.session, "last_input_at", None)
        if last_input:
            input_text = last_input.replace("\n", " ")[:_DETAIL_TEXT_LIMIT]
            input_time = format_time(last_input_at)
            line3 = Text(f"{detail_indent}[{input_time}]  in: {input_text}", style=input_style)
            lines.append(line3)

        # Line 4: [HH:MM:SS] out: <summary or tool activity>
        if self.active_tool:
            activity_time_str = format_time(self.session.last_activity)
            line4 = Text(f"{detail_indent}[{activity_time_str}] out: ", style=output_style)
            line4.append(
                truncate_text(self.active_tool, _DETAIL_TEXT_LIMIT),
                style=f"italic {get_agent_color(self.agent, 'muted')}",
            )
            lines.append(line4)
        elif self.last_output_summary:
            summary_at = getattr(self.session, "last_output_summary_at", None) or self.session.last_activity
            output_time = format_time(summary_at)
            output_text = self.last_output_summary.replace("\n", " ")[:_DETAIL_TEXT_LIMIT]
            line4 = Text(f"{detail_indent}[{output_time}] out: {output_text}", style=output_style)
            lines.append(line4)
        elif has_input_highlight or has_output_highlight:
            activity_time_str = format_time(self.session.last_activity)
            line4 = Text(f"{detail_indent}[{activity_time_str}] out: ", style=output_style)
            line4.append("...", style=f"italic bold {get_agent_color(self.agent, 'normal')}")
            lines.append(line4)

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
