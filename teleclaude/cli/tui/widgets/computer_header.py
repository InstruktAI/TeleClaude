"""Computer group header in session tree."""

from __future__ import annotations

from rich.text import Text
from textual.widget import Widget

from teleclaude.cli.tui.tree import ComputerDisplayInfo


class ComputerHeader(Widget):
    """Header row for a computer group in the sessions tree."""

    DEFAULT_CSS = """
    ComputerHeader {
        width: 100%;
        height: 1;
        padding: 0 1;
        text-style: bold;
    }
    """

    def __init__(self, data: ComputerDisplayInfo, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.data = data

    def render(self) -> Text:
        computer = self.data.computer
        name = computer.name
        status = computer.status
        count = self.data.session_count

        line = Text()
        if computer.is_local:
            line.append(f"⊙ {name}", style="bold")
        else:
            line.append(f"◎ {name}", style="bold")

        if status != "online":
            line.append(f"  [{status}]", style="dim italic")

        if count > 0:
            line.append(f"  ({count})", style="dim")

        return line
