"""Creation-record detail row within an expanded todo."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import CONNECTOR_COLOR
from teleclaude.cli.tui.todos import TodoItem

_CONNECTOR = Style(color=CONNECTOR_COLOR)
_DIM = Style(dim=True)


class TodoCreationRecordRow(TelecMixin, Widget):
    """Renders the Creation Record — entry_point, lineage, human_involved.

    The list-view row carries only the autonomous-filing marker glance; this
    is the detail-view drill-down that marker points at, mounted as the first
    child when a todo is expanded (see project/spec/domain/workflow). Renders
    the full `lineage` chain (root plus acting session, when present) — never
    just the root, which is the owner-chip/filter's reading, not this one's.
    """

    DEFAULT_CSS = """
    TodoCreationRecordRow {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        *,
        todo: TodoItem,
        slug: str,
        is_last: bool = False,
        tree_lines: list[bool] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.todo = todo
        self.slug = slug
        self.is_last = is_last
        self._tree_lines = tree_lines or []

    def render(self) -> Text:
        """Render entry_point, lineage, and human_involved as one detail line."""
        line = Text()
        line.append("  ", style=_CONNECTOR)
        for continues in self._tree_lines:
            line.append("│ " if continues else "  ", style=_CONNECTOR)
        connector = "└" if self.is_last else "├"
        line.append(f"{connector}─", style=_CONNECTOR)
        entry_point = self.todo.entry_point or "?"
        lineage = self.todo.lineage or "?"
        involved = "yes" if self.todo.human_involved else "no"
        line.append(f"created: {entry_point} · {lineage} · human_involved={involved}", style=_DIM)
        return line
