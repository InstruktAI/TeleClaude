"""Context-sensitive key hints bar."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget


class ActionBar(Widget):
    """Bottom bar showing available keyboard shortcuts for current context."""

    DEFAULT_CSS = """
    ActionBar {
        dock: bottom;
        width: 100%;
        height: 1;
        background: $surface-darken-2;
    }
    """

    active_view = reactive("sessions")
    has_selection = reactive(False)

    # Hint definitions per view
    _VIEW_HINTS: dict[str, list[tuple[str, str]]] = {
        "sessions": [
            ("↑↓", "navigate"),
            ("Space", "preview"),
            ("Space×2", "sticky"),
            ("Enter", "focus"),
            ("←→", "collapse"),
            ("+/-", "expand/collapse all"),
            ("n", "new"),
            ("k", "kill"),
            ("R", "restart"),
        ],
        "preparation": [
            ("↑↓", "navigate"),
            ("Enter", "expand/action"),
            ("+/-", "expand/collapse all"),
            ("p", "prepare"),
            ("s", "start work"),
        ],
        "jobs": [
            ("↑↓", "navigate"),
            ("Enter", "run"),
        ],
        "config": [
            ("Tab", "next field"),
            ("Enter", "edit"),
        ],
    }

    def render(self) -> Text:
        line = Text()
        hints = self._VIEW_HINTS.get(self.active_view, [])
        for i, (key, desc) in enumerate(hints):
            if i > 0:
                line.append("  ")
            line.append(f" {key} ", style="reverse")
            line.append(f" {desc}", style="dim")
        return line

    def watch_active_view(self, _value: str) -> None:
        self.refresh()
