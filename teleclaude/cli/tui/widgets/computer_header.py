"""Computer group header in session tree."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.tree import ComputerDisplayInfo


class ComputerHeader(TelecMixin, Widget):
    """Header row for a computer group — underlined name with session count."""

    class Pressed(Message):
        """Posted when a computer header is clicked."""

        def __init__(self, header: ComputerHeader) -> None:
            super().__init__()
            self.header = header

    DEFAULT_CSS = """
    ComputerHeader {
        width: 100%;
        height: auto;
        padding: 0 1;
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
        is_selected = self.has_class("selected")

        line = Text()
        if is_selected:
            base_style = Style(reverse=True)
        else:
            base_style = Style()

        line.append(f"\U0001f5a5  {name}", style=base_style)

        if status != "online":
            style = Style(reverse=True, italic=True) if is_selected else Style(dim=True, italic=True)
            line.append(f"  [{status}]", style=style)

        suffix = f"({count})" if count else ""
        if suffix:
            style = Style(reverse=True) if is_selected else Style(dim=True)
            line.append(f" {suffix}", style=style)

        # Thick separator line below computer name
        line.append("\n")
        content_width = max(self.size.width, 40)
        line.append("\u2501" * content_width, style=Style(bold=True, dim=True))

        return line

    def on_click(self, event: Click) -> None:
        """Post Pressed message when clicked."""
        event.stop()
        self.post_message(self.Pressed(self))
