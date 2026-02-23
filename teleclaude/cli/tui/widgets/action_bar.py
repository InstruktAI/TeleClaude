"""Context-sensitive key hints bar with submenu and global menu rows."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin


class ActionBar(TelecMixin, Widget):
    """3-row action bar: separator, context submenu, global shortcuts.

    Matches old curses TUI footer layout:
    Row 1: ─── separator line
    Row 2: [context-sensitive hints] — changes per active view
    Row 3: [global hints] — always shown, dimmed
    """

    DEFAULT_CSS = """
    ActionBar {
        width: 100%;
        height: 3;
    }
    """

    active_view = reactive("sessions")
    cursor_item_type = reactive("")  # "session" | "computer" | "project" | ""

    # Context-sensitive action bar per cursor item type (sessions view)
    _SESSION_CONTEXT: dict[str, str] = {
        "session": "[Space] Preview  [Enter] Focus  [\u2190/\u2192] Collapse/Expand  [R] Restart  [k] Kill",
        "computer": "[Enter] New Session  [n] New Session",
        "project": "[Enter] New Session  [n] New Session",
    }

    # Context hints per view (non-sessions tabs)
    _CONTEXT_BAR: dict[str, str] = {
        "preparation": "[Enter] Edit  [Space] Preview  [n] New Todo  [b] New Bug  [p] Prepare  [s] Start Work  [R] Remove",
        "jobs": "[Enter] Run",
        "config": "[Tab] Next Field  [Enter] Edit",
    }

    # Global shortcuts (row 3, always shown, dimmed)
    _GLOBAL_BAR = "[+/-] Expand/Collapse  [r] Refresh  [t] Colors  [q] Quit"

    def render(self) -> Text:
        result = Text()
        # Row 1: Separator line
        result.append("\u2500" * self.size.width, style="dim")
        result.append("\n")
        # Row 2: Context-sensitive — cursor-aware for sessions, static for others
        if self.active_view == "sessions":
            context = self._SESSION_CONTEXT.get(self.cursor_item_type, self._SESSION_CONTEXT["session"])
        else:
            context = self._CONTEXT_BAR.get(self.active_view, "")
        result.append(context)
        result.append("\n")
        # Row 3: Global shortcuts (dimmed)
        result.append(self._GLOBAL_BAR, style="dim")
        return result

    def watch_active_view(self, _value: str) -> None:
        self.refresh()

    def watch_cursor_item_type(self, _value: str) -> None:
        self.refresh()
