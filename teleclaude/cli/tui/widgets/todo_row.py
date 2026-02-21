"""Todo display row for preparation view with tree connectors and column-aligned properties."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import CONNECTOR_COLOR, is_dark_mode
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.core.next_machine.core import DOR_READY_THRESHOLD

_CONNECTOR = Style(color=CONNECTOR_COLOR)
_DIM = Style(dim=True)

# Status colors: dark/light table (like agent colors)
_STATUS_COLORS_DARK = {"draft": "color(244)", "ready": "color(71)", "active": "color(178)"}
_STATUS_COLORS_LIGHT = {"draft": "color(244)", "ready": "color(28)", "active": "color(136)"}

# Phase value colors
_OK_DARK = "color(71)"
_OK_LIGHT = "color(28)"
_GOLD_DARK = "color(178)"
_GOLD_LIGHT = "color(136)"

# Column gap between aligned properties
_COL_GAP = 2

# Muted slug color (missing artifacts)
_MUTED_DARK = "color(244)"
_MUTED_LIGHT = "color(102)"


def _ok_color() -> str:
    return _OK_DARK if is_dark_mode() else _OK_LIGHT


def _gold_color() -> str:
    return _GOLD_DARK if is_dark_mode() else _GOLD_LIGHT


def _muted_color() -> str:
    return _MUTED_DARK if is_dark_mode() else _MUTED_LIGHT


def _pad(text: Text, width: int) -> Text:
    """Pad a Text to a fixed width with dot leaders."""
    gap = max(0, width - len(text))
    if gap > 0:
        text.append("\u00b7" * gap, style=Style(color=_muted_color()))
    return text


class TodoRow(TelecMixin, Widget):
    """Single todo item row with tree connectors and column-aligned properties."""

    class Pressed(Message):
        """Posted when a todo row is clicked."""

        def __init__(self, todo_row: TodoRow) -> None:
            super().__init__()
            self.todo_row = todo_row

    DEFAULT_CSS = """
    TodoRow {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        todo: TodoItem,
        is_last: bool = False,
        slug_width: int = 0,
        col_widths: dict[str, int] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.todo = todo
        self.is_last = is_last
        self._slug_width = slug_width
        self._col_widths = col_widths or {}

    @staticmethod
    def compute_col_widths(todos: list[TodoItem]) -> dict[str, int]:
        """Compute column widths from actual data: max rendered length + gap.

        Column order: DOR | B | R | F | D
        """
        maxes: dict[str, int] = {"DOR": 0, "B": 0, "R": 0, "F": 0, "D": 0}
        for t in todos:
            if t.dor_score is not None:
                maxes["DOR"] = max(maxes["DOR"], len(f"DOR:{t.dor_score}"))
            bs = t.build_status
            if bs and bs != "pending":
                maxes["B"] = max(maxes["B"], len(f"B:{bs}"))
            rs = t.review_status
            if rs and rs != "pending":
                maxes["R"] = max(maxes["R"], len(f"R:{rs}"))
            if t.findings_count:
                maxes["F"] = max(maxes["F"], len(f"F:{t.findings_count}"))
            if t.deferrals_status:
                maxes["D"] = max(maxes["D"], len(f"D:{t.deferrals_status}"))
        return {k: (v + _COL_GAP if v > 0 else 0) for k, v in maxes.items()}

    @property
    def slug(self) -> str:
        return self.todo.slug

    def _status_style(self) -> Style:
        label = self.todo.status.display_label
        colors = _STATUS_COLORS_DARK if is_dark_mode() else _STATUS_COLORS_LIGHT
        color = colors.get(label, colors["draft"])
        bold = label == "active"
        return Style(color=color, bold=bold)

    def _build_col(self, label: str, value: str, width: int, value_style: Style) -> Text:
        """Render a fixed-width column. Empty value → blank padding for alignment."""
        col = Text()
        if value:
            col.append(f"{label}:", style=Style())
            col.append(value, style=value_style)
        return _pad(col, width)

    def _build_columns(self) -> Text:
        """Build aligned property columns. Order: DOR | B | R | F | D."""
        result = Text()
        ok = _ok_color()
        gold = _gold_color()
        w = self._col_widths

        # DOR (first)
        dor = self.todo.dor_score
        dor_color = ok if dor is not None and dor >= DOR_READY_THRESHOLD else gold
        result.append_text(
            self._build_col("DOR", str(dor) if dor is not None else "", w.get("DOR", 0), Style(color=dor_color))
        )

        # B
        bs = self.todo.build_status
        b_val = bs if bs and bs != "pending" else ""
        result.append_text(
            self._build_col("B", b_val, w.get("B", 0), Style(color=ok if bs == "complete" else gold, bold=True))
        )

        # R
        rs = self.todo.review_status
        r_val = rs if rs and rs != "pending" else ""
        result.append_text(
            self._build_col("R", r_val, w.get("R", 0), Style(color=ok if rs == "approved" else gold, bold=True))
        )

        # F (findings)
        fc = self.todo.findings_count
        result.append_text(self._build_col("F", str(fc) if fc else "", w.get("F", 0), Style(color=gold, bold=True)))

        # D (deferrals)
        ds = self.todo.deferrals_status
        result.append_text(self._build_col("D", ds or "", w.get("D", 0), _DIM))

        return result

    def render(self) -> Text:
        line = Text()
        is_selected = self.has_class("selected")

        # Tree connector + status dot: draft=space, ready=green ●, active=gold ●
        line.append("  \u251c\u2500", style=_CONNECTOR)
        status_label = self.todo.status.display_label
        if status_label == "draft":
            line.append("\u25a1", style=self._status_style())
        else:
            line.append("\u25a0", style=self._status_style())
        line.append(" ")

        # Slug — muted when missing artifacts, reverse when selected
        missing_artifacts = not self.todo.has_requirements or not self.todo.has_impl_plan
        if is_selected:
            slug_style = Style(reverse=True)
        elif missing_artifacts:
            slug_style = Style(color=_muted_color())
        else:
            slug_style = Style()
        line.append(self.todo.slug, style=slug_style)

        # Dot padding from slug to columns
        dot_count = max(1, self._slug_width - len(self.todo.slug) + 2)
        line.append("\u00b7" * dot_count, style=Style(color=_muted_color()))

        # Property columns (DOR first)
        line.append_text(self._build_columns())

        # Dependency suffix
        if self.todo.after:
            dep_text = ", ".join(self.todo.after)
            line.append(f"  \u2190 {dep_text}", style=_DIM)

        return line

    def on_click(self, event: Click) -> None:
        """Post Pressed message when clicked."""
        event.stop()
        self.post_message(self.Pressed(self))
