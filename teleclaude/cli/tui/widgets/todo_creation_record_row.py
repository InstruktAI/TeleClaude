"""Creator-session navigation row within an expanded todo."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.events import Click
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.creator_session import CreatorRowState
from teleclaude.cli.tui.messages import CreateSessionRequest, JumpToSession
from teleclaude.cli.tui.theme import CONNECTOR_COLOR
from teleclaude.cli.tui.todos import TodoItem

# Textual injects the content (column, row) of a click into the click's style
# meta under this key; the row uses it to map a click to a sub-region.
_CLICK_OFFSET_META = "offset"

_CONNECTOR = Style(color=CONNECTOR_COLOR)
_DIM = Style(dim=True)
_BOLD = Style(bold=True)

_LABEL_PREFIX = "created in: "
_REVIVE_SEPARATOR = " - "
_REVIVE_LABEL = "revive"


class CreatorSessionRow(TelecMixin, Widget):
    """Renders the creator-session navigation affordance for an expanded todo.

    Mounted as the first child when a todo is expanded and its creation
    lineage carries an acting TeleClaude session id (see
    project/spec/feature/tui/todo-session-cross-navigation). A navigation
    affordance, not an authorship claim: a live session renders its id bold
    and clickable (jump); a retained closed session renders inert id text
    plus a bold clickable "revive"; a hard-deleted session renders inert text
    with no click target at all.
    """

    DEFAULT_CSS = """
    CreatorSessionRow {
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
        state: CreatorRowState,
        is_last: bool = False,
        tree_lines: list[bool] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.todo = todo
        self.slug = slug
        self.state = state
        self.is_last = is_last
        self._tree_lines = tree_lines or []
        self._click_region: tuple[int, int] | None = None

    def render(self) -> Text:
        """Render the creator-session line for this row's live/closed/missing state."""
        line = Text()
        line.append("  ", style=_CONNECTOR)
        for continues in self._tree_lines:
            line.append("│ " if continues else "  ", style=_CONNECTOR)
        connector = "└" if self.is_last else "├"
        line.append(f"{connector}─", style=_CONNECTOR)
        line.append(_LABEL_PREFIX, style=_DIM)

        self._click_region = None
        session_id = self.state.session_id
        if self.state.status == "live":
            start = line.cell_len
            line.append(session_id, style=_BOLD)
            self._click_region = (start, line.cell_len)
        elif self.state.status == "closed":
            line.append(session_id, style=_DIM)
            line.append(_REVIVE_SEPARATOR, style=_DIM)
            start = line.cell_len
            line.append(_REVIVE_LABEL, style=_BOLD)
            self._click_region = (start, line.cell_len)
        else:
            line.append(session_id, style=_DIM)
        return line

    def _click_column(self, event: Click) -> int | None:
        """Return the content column of a click, or None when unavailable."""
        offset = event.style.meta.get(_CLICK_OFFSET_META) if event.style else None
        if isinstance(offset, tuple) and len(offset) == 2:
            return int(offset[0])
        return None

    def on_click(self, event: Click) -> None:
        """Route a click on the styled span to a jump or a revive-and-navigate request."""
        event.stop()
        column = self._click_column(event)
        if column is None or self._click_region is None:
            return
        if not (self._click_region[0] <= column < self._click_region[1]):
            return
        if self.state.status == "live":
            self.post_message(JumpToSession(self.state.session_id))
        elif self.state.status == "closed":
            self.post_message(
                CreateSessionRequest(
                    computer=self.state.computer or "local",
                    project_path=self.todo.project_path or "",
                    revive_session_id=self.state.session_id,
                    navigate_after_revive=True,
                )
            )
