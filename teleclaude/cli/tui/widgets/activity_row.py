"""Base row widget for session and job list items."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget


class ActivityRow(Widget):
    """Base row with: left badge, center title+subtitle, right status+time.

    Subclasses override render() to build their specific layout.
    """

    DEFAULT_CSS = """
    ActivityRow {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    """

    title = reactive("")
    subtitle = reactive("")
    status_text = reactive("")
    timestamp = reactive("")

    def render(self) -> Text:
        line = Text()
        if self.title:
            line.append(self.title)
        if self.subtitle:
            line.append(f"  {self.subtitle}", style="dim")
        if self.status_text:
            line.append(f"  {self.status_text}", style="italic")
        if self.timestamp:
            line.append(f"  {self.timestamp}", style="dim")
        return line
