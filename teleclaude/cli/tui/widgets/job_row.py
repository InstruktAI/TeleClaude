"""Job display row."""

from __future__ import annotations

from rich.text import Text
from textual.widget import Widget

from teleclaude.cli.models import JobInfo
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.utils.formatters import format_relative_time


class JobRow(TelecMixin, Widget):
    """Single job row in the jobs list."""

    DEFAULT_CSS = """
    JobRow {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, job: JobInfo, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.job = job

    def render(self) -> Text:
        line = Text()
        # Status indicator
        status = self.job.status
        if status == "running":
            line.append("● ", style="green")
        elif status == "failed":
            line.append("✘ ", style="red")
        else:
            line.append("· ", style="dim")

        # Name
        line.append(self.job.name, style="bold" if status == "running" else "")

        # Type
        line.append(f"  [{self.job.type}]", style="dim")

        # Schedule
        if self.job.schedule:
            line.append(f"  {self.job.schedule}", style="dim italic")

        # Last run
        if self.job.last_run:
            line.append(f"  {format_relative_time(self.job.last_run)} ago", style="dim")

        return line
