"""Two-line footer hints widget (context + global)."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.events import MouseEvent
from textual.widget import Widget


class HintsFooter(Widget):
    """Render active bindings in two rows.

    Row 1: Context-aware bindings (focused view / child widgets).
    Row 2: Global bindings (app-level bindings).
    """

    DEFAULT_CSS = """
    HintsFooter {
        width: 100%;
        height: 2;
    }
    """

    def on_mount(self) -> None:
        self.screen.bindings_updated_signal.subscribe(self, self._on_bindings_changed)

    def on_unmount(self) -> None:
        self.screen.bindings_updated_signal.unsubscribe(self)

    def _on_bindings_changed(self, _screen: object) -> None:
        if self.app.app_focus:
            self.refresh()

    def _format_item(self, binding: Binding, *, enabled: bool, tooltip: str) -> Text:
        key = self.app.get_key_display(binding)
        label = tooltip or binding.description

        text = Text()
        key_style = Style(bold=True, dim=not enabled)
        label_style = Style(dim=not enabled)
        text.append(str(key), style=key_style)
        if label:
            text.append(" ")
            text.append(label, style=label_style)
        return text

    def _collect_rows(self) -> tuple[list[tuple[Binding, bool, str]], list[tuple[Binding, bool, str]]]:
        active_bindings = self.screen.active_bindings

        context_row: list[tuple[Binding, bool, str]] = []
        global_row: list[tuple[Binding, bool, str]] = []
        seen_context_actions: set[str] = set()
        seen_global_actions: set[str] = set()

        for node, binding, enabled, tooltip in active_bindings.values():
            if not binding.show:
                continue

            is_global = node is self.app
            seen = seen_global_actions if is_global else seen_context_actions
            if binding.action in seen:
                continue
            seen.add(binding.action)

            item = (binding, enabled, tooltip)
            if is_global:
                global_row.append(item)
            else:
                context_row.append(item)

        return context_row, global_row

    def render(self) -> Text:
        context_row, global_row = self._collect_rows()

        line1 = Text()
        if context_row:
            for idx, (binding, enabled, tooltip) in enumerate(context_row):
                if idx:
                    line1.append("  ")
                line1.append_text(self._format_item(binding, enabled=enabled, tooltip=tooltip))
        else:
            line1.append("No context actions", style=Style(dim=True))

        line2 = Text(style=Style(dim=True))
        if global_row:
            for idx, (binding, enabled, tooltip) in enumerate(global_row):
                if idx:
                    line2.append("  ")
                line2.append_text(self._format_item(binding, enabled=enabled, tooltip=tooltip))
        else:
            line2.append("No global actions", style=Style(dim=True))

        return Text.assemble(line1, "\n", line2)

    def on_mouse_down(self, _event: MouseEvent) -> None:
        """Keep footer non-interactive for now (display only)."""
        return
