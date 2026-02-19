"""Project group header in session/preparation tree."""

from __future__ import annotations

from rich.text import Text
from textual.widget import Widget

from teleclaude.cli.models import ProjectInfo


class ProjectHeader(Widget):
    """Header row for a project group."""

    DEFAULT_CSS = """
    ProjectHeader {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, project: ProjectInfo, session_count: int = 0, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.project = project
        self.session_count = session_count

    def render(self) -> Text:
        line = Text()
        # Show project name or last path component
        name = self.project.name or self.project.path.rstrip("/").rsplit("/", 1)[-1]
        line.append(f"  ├ {name}", style="bold dim")

        if self.project.description:
            line.append(f"  {self.project.description}", style="dim italic")

        if self.session_count > 0:
            line.append(f"  ({self.session_count})", style="dim")

        return line
