"""Project group header in session/preparation tree."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.models import ProjectInfo
from teleclaude.cli.tui.utils.formatters import shorten_path


class ProjectHeader(Widget):
    """Header row for a project group — shows path with separator line."""

    DEFAULT_CSS = """
    ProjectHeader {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    """

    terminal_width = reactive(80)

    def __init__(self, project: ProjectInfo, session_count: int = 0, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.project = project
        self.session_count = session_count

    def on_resize(self, event: object) -> None:
        self.terminal_width = self.size.width

    def render(self) -> Text:
        line = Text()
        path = shorten_path(self.project.path)
        suffix = f"({self.session_count})" if self.session_count else ""
        # Mute empty projects
        style = "dim" if not self.session_count else ""
        line.append(f"📁 {path}", style=style)
        if suffix:
            line.append(f" {suffix}", style="dim")
        line.append("\n")
        # Separator line
        sep_width = max(self.terminal_width, 40)
        line.append("─" * sep_width, style="dim")
        return line
