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
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.utils.formatters import format_relative_time
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    coerce_lifecycle_phase,
    is_settled_ok_phase,
)

_CONNECTOR = Style(color=CONNECTOR_COLOR)
_DIM = Style(dim=True)

_PHASE_PREFIX_LIFECYCLE = "P"
_PHASE_PREFIX_INTEGRATION = "I"
_PHASE_PREFIX_KIND = "K"

_INTEGRATION_LABEL_STARTED = "started"
_INTEGRATION_LABEL_DELIVERED = "delivered"
_INTEGRATION_LABEL_READY = "ready"

_TODO_STATUS_DRAFT = "draft"
_TODO_STATUS_READY = "ready"
_TODO_STATUS_ACTIVE = "active"
_TODO_STATUS_PENDING = "pending"
_TODO_STATUS_COMPLETE = "complete"
_TODO_STATUS_APPROVED = "approved"
_TODO_STATUS_DELIVERED = "delivered"
_TODO_STATUS_ICEBOX = "icebox"
_TODO_STATUS_REMOVED = "trashed"

_LIFECYCLE_PHASE_LABELS: dict[LifecyclePhase, str] = {
    LifecyclePhase.DRAFT: "intake",
    LifecyclePhase.PRD_DRAFTING: "prd drafting",
    LifecyclePhase.PRD_HUMAN_APPROVAL: "prd approval",
    LifecyclePhase.ARCHITECTURE_DRAFTING: "arch drafting",
    LifecyclePhase.ARCHITECTURE_REVIEW: "arch review",
    LifecyclePhase.DIAGNOSE: "diagnose",
    LifecyclePhase.PLAN_DRAFTING: "plan drafting",
    LifecyclePhase.PLAN_REVIEW: "plan review",
    LifecyclePhase.PREPARED: "prepared",
    LifecyclePhase.BLOCKED: "blocked",
}

# Work-lane lifecycle_phase → (build_status, review_status) for the B/R columns.
# This is the renderer's final-stage projection from canonical phase to the
# legacy two-column display. The backend ships lifecycle_phase as-is; this
# mapping reproduces the exact UI output without consulting derive_* helpers.
_PHASE_TO_BUILD_STATUS: dict[LifecyclePhase, str] = {
    LifecyclePhase.BUILD_STARTED: "started",
    LifecyclePhase.BUILD_COMPLETE: "complete",
    LifecyclePhase.REVIEW_CHANGES_REQUESTED: "complete",
    LifecyclePhase.REVIEW_APPROVED: "complete",
    LifecyclePhase.FINALIZE_READY: "complete",
}
_PHASE_TO_REVIEW_STATUS: dict[LifecyclePhase, str] = {
    LifecyclePhase.BUILD_COMPLETE: "pending",
    LifecyclePhase.REVIEW_CHANGES_REQUESTED: "changes_requested",
    LifecyclePhase.REVIEW_APPROVED: "approved",
    LifecyclePhase.FINALIZE_READY: "approved",
}


def _phase_build_status(lifecycle_phase: str | None) -> str | None:
    """Look up the B-column value for the given lifecycle phase."""
    phase = coerce_lifecycle_phase(lifecycle_phase)
    if phase is None:
        return None
    return _PHASE_TO_BUILD_STATUS.get(phase)


def _phase_review_status(lifecycle_phase: str | None) -> str | None:
    """Look up the R-column value for the given lifecycle phase."""
    phase = coerce_lifecycle_phase(lifecycle_phase)
    if phase is None:
        return None
    return _PHASE_TO_REVIEW_STATUS.get(phase)


_FINALIZE_LABEL_READY = "ready"


def lifecycle_phase_label(phase: str | None) -> tuple[str, str, str] | None:
    """Return the canonical lifecycle column tuple for a todo, if any."""
    lifecycle_phase = coerce_lifecycle_phase(phase)
    if lifecycle_phase is None:
        return None
    value = _LIFECYCLE_PHASE_LABELS.get(lifecycle_phase)
    if not value:
        return None
    color = _ok_color() if is_settled_ok_phase(phase) else _gold_color()
    return _PHASE_PREFIX_LIFECYCLE, value, color


def integration_phase_label(phase: str | None, finalize_status: str | None) -> tuple[str, str, str] | None:
    """Return the integration-phase column tuple for a todo, if any.

    Only two stamped values are recognized: 'started' and 'delivered'.
    Legacy/stale values from the old 12-phase mirror are ignored — roadmap.py
    maps them to canonical values before they reach here.
    """
    if phase == "started":
        return _PHASE_PREFIX_INTEGRATION, _INTEGRATION_LABEL_STARTED, _ok_color()
    if phase == "delivered":
        return _PHASE_PREFIX_INTEGRATION, _INTEGRATION_LABEL_DELIVERED, _muted_color()
    if not phase:
        finalize_to_label = {
            _FINALIZE_LABEL_READY: _INTEGRATION_LABEL_READY,
        }
        label = finalize_to_label.get(finalize_status or "")
        return (_PHASE_PREFIX_INTEGRATION, label, _ok_color()) if label else None
    return None


# Status colors: dark/light table (like agent colors)
_STATUS_COLORS_DARK = {
    _TODO_STATUS_DRAFT: "color(244)",
    _TODO_STATUS_READY: "color(71)",
    _TODO_STATUS_ACTIVE: "color(178)",
    _TODO_STATUS_DELIVERED: "color(244)",
    _TODO_STATUS_ICEBOX: "color(74)",
    _TODO_STATUS_REMOVED: "color(161)",
}
_STATUS_COLORS_LIGHT = {
    _TODO_STATUS_DRAFT: "color(244)",
    _TODO_STATUS_READY: "color(28)",
    _TODO_STATUS_ACTIVE: "color(136)",
    _TODO_STATUS_DELIVERED: "color(102)",
    _TODO_STATUS_ICEBOX: "color(31)",
    _TODO_STATUS_REMOVED: "color(125)",
}

# Phase value colors
_OK_DARK = "color(71)"
_OK_LIGHT = "color(28)"
_GOLD_DARK = "color(178)"
_GOLD_LIGHT = "color(136)"
# Column gap between aligned properties
_COL_GAP = 2

# Horizontal padding from CSS `padding: 0 1` (1 left + 1 right)
_WIDGET_PADDING_HORZ = 2

# Fixed character overhead per row before slug and columns:
# "  " (2) + connector "├─"/"└─" (2) + status icon (1) + space (1) = 6, plus max_depth*2 for tree lines
_ROW_FIXED_OVERHEAD = 6


def row_content_width(slug_width: int, max_depth: int, col_width: int) -> int:
    """Canonical natural content width for todo rows and icebox separators.

    This is the shared data-driven width before any pane-width degradation.
    Does not include widget CSS padding — subtract _WIDGET_PADDING_HORZ for the
    actual available rendering area.
    """
    return _ROW_FIXED_OVERHEAD + 2 + slug_width + max_depth * 2 + col_width


# Icebox color (light blue)
_ICEBOX_DARK = "color(74)"
_ICEBOX_LIGHT = "color(31)"
_TRASHED_DARK = "color(161)"
_TRASHED_LIGHT = "color(125)"

# Muted slug color (missing artifacts)
_MUTED_DARK = "color(244)"
_MUTED_LIGHT = "color(102)"


def _ok_color() -> str:
    """Return the theme-aware success color."""
    return _OK_DARK if is_dark_mode() else _OK_LIGHT


def _gold_color() -> str:
    """Return the theme-aware warning color."""
    return _GOLD_DARK if is_dark_mode() else _GOLD_LIGHT


def _kind_color() -> str:
    """Return the theme-aware color for the K:<kind> tag."""
    return "color(109)" if is_dark_mode() else "color(66)"


def _icebox_color() -> str:
    """Return the theme-aware icebox color (light blue)."""
    return _ICEBOX_DARK if is_dark_mode() else _ICEBOX_LIGHT


def _trashed_color() -> str:
    """Return the theme-aware trashed color (maroon)."""
    return _TRASHED_DARK if is_dark_mode() else _TRASHED_LIGHT


def _muted_color() -> str:
    """Return the theme-aware muted color."""
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
        tree_lines: list[bool] | None = None,
        max_depth: int = 0,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.todo = todo
        self.is_last = is_last
        self._slug_width = slug_width
        self._col_widths = col_widths or {}
        self._tree_lines = tree_lines or []
        self._max_depth = max_depth

    @staticmethod
    def compute_col_widths(todos: list[TodoItem]) -> dict[str, int]:
        """Compute column widths from actual data: max rendered length + gap.

        Column order: K | P | I | B | R | D
        """
        maxes: dict[str, int] = {"K": 0, "P": 0, "I": 0, "B": 0, "R": 0, "D": 0}
        for t in todos:
            kind_label = t.kind if t.kind else "unknown"
            maxes["K"] = max(maxes["K"], len(f"{_PHASE_PREFIX_KIND}:{kind_label}"))
            if t.status == TodoStatus.ICEBOX:
                maxes["P"] = max(maxes["P"], len(f"{_PHASE_PREFIX_LIFECYCLE}:icebox"))
                continue
            if t.kind is None:
                maxes["P"] = max(maxes["P"], len(f"{_PHASE_PREFIX_LIFECYCLE}:classify"))
                continue
            p_result = lifecycle_phase_label(t.lifecycle_phase)
            if p_result is not None:
                p_prefix, p_value, _ = p_result
                maxes["P"] = max(maxes["P"], len(f"{p_prefix}:{p_value}"))
            i_result = integration_phase_label(t.integration_phase, t.finalize_status)
            if i_result is not None:
                i_prefix, i_value, _ = i_result
                maxes["I"] = max(maxes["I"], len(f"{i_prefix}:{i_value}"))
            bs = _phase_build_status(t.lifecycle_phase)
            if bs and bs != _TODO_STATUS_PENDING:
                maxes["B"] = max(maxes["B"], len(f"B:{bs}"))
            rs = _phase_review_status(t.lifecycle_phase)
            if rs and rs != _TODO_STATUS_PENDING:
                maxes["R"] = max(maxes["R"], len(f"R:{rs}"))
            if t.deferrals_status:
                maxes["D"] = max(maxes["D"], len(f"D:{t.deferrals_status}"))
        sized = {k: (v + _COL_GAP if v > 0 else 0) for k, v in maxes.items()}
        # K renders first on every row and is orthogonal to the phase/work columns.
        k = sized["K"]
        path_prepare = k + sized["P"]
        path_integration = k + sized["P"]  # I renders in P slot
        path_work = k + sized["B"] + sized["R"] + sized["D"]
        sized["_max"] = max(path_prepare, path_integration, path_work) + 1  # +1 trailing dot
        return sized

    @property
    def slug(self) -> str:
        """Expose the todo slug for parent list widgets."""
        return self.todo.slug

    def _status_style(self) -> Style:
        # Status is authoritative from the projection (holders already carry their
        # leaf-derived status). The TUI never re-derives it.
        label = self.todo.status.display_label
        if self.todo.integration_phase == "started":
            label = _TODO_STATUS_ACTIVE
        colors = _STATUS_COLORS_DARK if is_dark_mode() else _STATUS_COLORS_LIGHT
        color = colors.get(label, colors[_TODO_STATUS_DRAFT])
        bold = label == _TODO_STATUS_ACTIVE
        return Style(color=color, bold=bold)

    def _build_col(self, label: str, value: str, width: int, value_style: Style) -> Text:
        """Render a fixed-width column. Empty value -> blank padding for alignment."""
        col = Text()
        if value:
            if label:
                col.append(f"{label}:", style=Style())
            col.append(value, style=value_style)
        return _pad(col, width)

    def _total_col_width(self) -> int:
        """Max rendered column width across all paths — the target for uniform padding."""
        return self._col_widths.get("_max", 0)

    def _build_columns(self) -> Text:
        """Build aligned columns. K:<kind> renders first, then phase (P/I) or work (B/R/D)."""
        target = self._total_col_width()

        # Holders show no columns — status is the projection's leaf aggregate.
        if self.todo.is_holder:
            return _pad(Text(), target)

        w = self._col_widths
        result = Text()
        # K:<kind> is orthogonal to phase and renders first on every non-holder row.
        result.append_text(
            self._build_col(
                _PHASE_PREFIX_KIND, self.todo.kind or "unknown", w.get("K", 0), Style(color=_kind_color(), bold=True)
            )
        )

        # Icebox items show P:icebox only — no work-phase columns
        if self.todo.status == TodoStatus.ICEBOX:
            result.append_text(
                self._build_col(
                    _PHASE_PREFIX_LIFECYCLE, "icebox", w.get("P", 0), Style(color=_icebox_color(), bold=True)
                )
            )
            return _pad(result, target)

        # Trashed items show T:age only
        if self.todo.status == TodoStatus.REMOVED:
            age = format_relative_time(self.todo.removed_at) if self.todo.removed_at else ""
            result.append_text(self._build_col("T", age, w.get("P", 0), Style(color=_trashed_color(), bold=True)))
            return _pad(result, target)

        if self.todo.kind is None:
            result.append_text(
                self._build_col(
                    _PHASE_PREFIX_LIFECYCLE, "classify", w.get("P", 0), Style(color=_gold_color(), bold=True)
                )
            )
            return _pad(result, target)

        ok = _ok_color()
        gold = _gold_color()

        # Phase detection: top-to-bottom, first match wins.

        bs = _phase_build_status(self.todo.lifecycle_phase)
        rs = _phase_review_status(self.todo.lifecycle_phase)

        # 1. Active prepare lifecycle phase
        p_result = lifecycle_phase_label(self.todo.lifecycle_phase)
        if p_result is not None:
            p_label, p_value, p_color = p_result
            result.append_text(self._build_col(p_label, p_value, w.get("P", 0), Style(color=p_color, bold=True)))
            return _pad(result, target)

        # 2. Active or queued integration phase — render in the P column slot for alignment
        i_result = integration_phase_label(self.todo.integration_phase, self.todo.finalize_status)
        if i_result is not None:
            i_label, i_value, i_color = i_result
            result.append_text(self._build_col(i_label, i_value, w.get("P", 0), Style(color=i_color, bold=True)))
            return _pad(result, target)

        # 3. Work phase (build != pending) — existing B/R/D path
        if bs is not None and bs != _TODO_STATUS_PENDING:
            b_val = bs if bs and bs != _TODO_STATUS_PENDING else ""
            result.append_text(
                self._build_col(
                    "B", b_val, w.get("B", 0), Style(color=ok if bs == _TODO_STATUS_COMPLETE else gold, bold=True)
                )
            )

            r_val = rs if rs and rs != _TODO_STATUS_PENDING else ""
            result.append_text(
                self._build_col(
                    "R", r_val, w.get("R", 0), Style(color=ok if rs == _TODO_STATUS_APPROVED else gold, bold=True)
                )
            )

            ds = self.todo.deferrals_status
            result.append_text(self._build_col("D", ds or "", w.get("D", 0), _DIM))

            return _pad(result, target)

        # 4. Ready/pending state — no phase/work columns
        return _pad(result, target)

    def render(self) -> Text:
        """Render the tree prefix, slug, and aligned property columns."""
        line = Text(no_wrap=True)
        is_selected = self.has_class("selected")

        # Tree prefix: leading margin + ancestor continuation lines + own connector
        line.append("  ", style=_CONNECTOR)
        for continues in self._tree_lines:
            line.append("\u2502 " if continues else "  ", style=_CONNECTOR)
        line.append("\u2514\u2500" if self.is_last else "\u251c\u2500", style=_CONNECTOR)
        status_label = self.todo.status.display_label
        if status_label == _TODO_STATUS_DRAFT:
            line.append("\u25a1", style=self._status_style())
        elif status_label == _TODO_STATUS_REMOVED:
            line.append("\u2715", style=self._status_style())
        else:
            line.append("\u25a0", style=self._status_style())
        line.append(" ")

        if is_selected:
            slug_style = Style(reverse=True)
        else:
            slug_style = Style()
        line.append(self.todo.slug, style=slug_style)

        # Dot padding from slug to columns (compensate for indent so columns align)
        indent_compensation = (self._max_depth - len(self._tree_lines)) * 2
        dot_count = max(1, self._slug_width - len(self.todo.slug) + 2 + indent_compensation)

        # Graceful degradation: shrink dot leaders when pane is narrower than content
        outer_w = self.outer_size.width
        available = outer_w - _WIDGET_PADDING_HORZ if outer_w > 0 else 0
        if outer_w > 0:
            prefix_width = 2 + len(self._tree_lines) * 2 + 2 + 1 + 1  # "  " + tree + "├─" + icon + " "
            col_w = self._total_col_width()
            max_dots = max(0, available - prefix_width - len(self.todo.slug) - col_w)
            dot_count = min(dot_count, max_dots)

        line.append("\u00b7" * dot_count, style=Style(color=_muted_color()))

        # Property columns
        line.append_text(self._build_columns())

        # Fill to the current window width, reserving exactly 2 trailing spaces
        # (not dots) as the right gutter. Responsive to the live pane width.
        if outer_w > 0:
            fill_to = max(0, available - 2)
            gap = fill_to - len(line)
            if gap > 0:
                line.append("·" * gap, style=Style(color=_muted_color()))
            line.truncate(fill_to)
            line.append("  ")

        return line

    def on_click(self, event: Click) -> None:
        """Post Pressed message when clicked."""
        event.stop()
        self.post_message(self.Pressed(self))
