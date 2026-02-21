"""Project group header in session/preparation tree."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widget import Widget

from teleclaude.cli.models import ProjectInfo
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import CONNECTOR_COLOR, NEUTRAL_MUTED_COLOR
from teleclaude.cli.tui.utils.formatters import shorten_path


class ProjectHeader(TelecMixin, Widget):
    """Header row for a project group — 1-space indent, path with separator line."""

    class Pressed(Message):
        """Posted when a project header is clicked."""

        def __init__(self, header: ProjectHeader) -> None:
            super().__init__()
            self.header = header

    DEFAULT_CSS = """
    ProjectHeader {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(
        self, project: ProjectInfo, session_count: int = 0, show_connector: bool = True, **kwargs: object
    ) -> None:
        super().__init__(**kwargs)
        self.project = project
        self.session_count = session_count
        self.show_connector = show_connector

    # Connector column — matches SessionRow._connector_col for depth=2
    CONNECTOR_COL = 2

    def render(self) -> Text:
        line = Text()
        path = shorten_path(self.project.path)
        suffix = f"({self.session_count})" if self.session_count else ""
        is_selected = self.has_class("selected")

        if is_selected:
            base_style = Style(reverse=True)
        elif not self.session_count:
            base_style = Style(color=NEUTRAL_MUTED_COLOR)
        else:
            base_style = Style()

        # 1-space indent so folder aligns above session [N] badges
        line.append(" ")
        name = self.project.name
        if name:
            line.append(f"\U0001f4c1 {name} - {path}", style=base_style)
        else:
            line.append(f"\U0001f4c1 {path}", style=base_style)
        if suffix:
            line.append(f" {suffix}", style=base_style)
        line.append("\n")
        # Separator line
        connector_style = Style(color=CONNECTOR_COLOR)
        content_width = max(self.size.width, 40)
        if self.show_connector:
            line.append("\u2500" * content_width, style=connector_style)
        return line

    def on_click(self, event: Click) -> None:
        """Post Pressed message when clicked."""
        event.stop()
        self.post_message(self.Pressed(self))
