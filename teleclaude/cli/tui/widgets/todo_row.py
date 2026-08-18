"""Todo display row for preparation view with tree connectors and column-aligned properties."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.messages import ChipFilterToggle, JumpToSession
from teleclaude.cli.tui.theme import CONNECTOR_COLOR, is_dark_mode
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.utils.formatters import format_relative_time
from teleclaude.cli.tui.widgets.chip import PersonChip, resolve_person_chip
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    coerce_lifecycle_phase,
    is_settled_ok_phase,
    pending_approval_gate,
)
from teleclaude.types.creation_record import Lineage

# Textual injects the content (column, row) of a click into the click's style
# meta under this key; the row uses it to map a click to a sub-region.
_CLICK_OFFSET_META = "offset"

_CONNECTOR = Style(color=CONNECTOR_COLOR)
_DIM = Style(dim=True)

_PHASE_PREFIX_LIFECYCLE = "P"
_PHASE_PREFIX_INTEGRATION = "I"
_PHASE_PREFIX_KIND = ""

_INTEGRATION_LABEL_STARTED = "started"
_INTEGRATION_LABEL_DELIVERED = "delivered"
_INTEGRATION_LABEL_READY = "ready"

_TODO_STATUS_DRAFT = "draft"
_TODO_STATUS_READY = "ready"
_TODO_STATUS_ACTIVE = "active"
_TODO_STATUS_DELIVERED = "delivered"
_TODO_STATUS_ICEBOX = "icebox"
_TODO_STATUS_REMOVED = "trashed"

_LIFECYCLE_PHASE_LABELS: dict[LifecyclePhase, str] = {
    LifecyclePhase.DRAFT: "intake",
    LifecyclePhase.PRD_DRAFTING: "prd draft",
    LifecyclePhase.PRD_REVIEW: "prd revw",
    LifecyclePhase.PRD_HUMAN_APPROVAL: "prd apprvl",
    LifecyclePhase.ARCHITECTURE_DRAFTING: "arch draft",
    LifecyclePhase.ARCHITECTURE_REVIEW: "arch revw",
    LifecyclePhase.DIAGNOSE: "diagnose",
    LifecyclePhase.PLAN_DRAFTING: "plan draft",
    LifecyclePhase.PLAN_REVIEW: "plan revw",
    LifecyclePhase.TASK_PLAN_DRAFTING: "task plan",
    LifecyclePhase.PREPARED: "prepared",
    LifecyclePhase.BLOCKED: "blocked",
    LifecyclePhase.TASK_RUNNING: "task run",
}

_KIND_DISPLAY: dict[str, str] = {
    "feature": "feat",
    "change": "chng",
    "bug": "bug",
    "task": "task",
}

_PHASE_PREFIX_WORK = "W"

# Work-lane lifecycle_phase → single W-column station label. Every label names
# the step the row is at or owes — same semantics as the prepare-lane labels.
_WORK_PHASE_LABELS: dict[LifecyclePhase, str] = {
    LifecyclePhase.BUILD_STARTED: "build",
    LifecyclePhase.BUILD_COMPLETE: "review",
    LifecyclePhase.REVIEW_CHANGES_REQUESTED: "rework",
    LifecyclePhase.REVIEW_APPROVED: "finalize",
    LifecyclePhase.FINALIZE_READY: "finalize",
}


# Gate/lock glyph for a held todo, rendered in the row's dedicated last column.
_HOLD_ICON = "\U0001f512"

# Display (cell) width of the hold glyph. `🔒` is an emoji: len("🔒") == 1 but it
# occupies 2 terminal cells. The module's width math is len()-based, so the held
# column is sized and padded in cells explicitly to avoid a 1-cell drift.
_HOLD_ICON_CELLS = 2

# Marker for a todo an agent filed on its own: entry_point is "agent" and no human
# was declared involved — the "started without me" audit glance. An undeclared human
# alone does not qualify; a human-, TUI-, or CLI-filed todo never carries the marker.
_AUTONOMOUS_ICON = "\U0001f916"
_AUTONOMOUS_ICON_CELLS = 2


def _approval_pending(todo: TodoItem) -> bool:
    if todo.status in {TodoStatus.ICEBOX, TodoStatus.DELIVERED, TodoStatus.REMOVED}:
        return False
    if _task_authorization_pending(todo):
        return True
    return pending_approval_gate({"kind": todo.kind, "lifecycle_phase": todo.lifecycle_phase}) is not None


def _task_authorization_pending(todo: TodoItem) -> bool:
    if todo.kind != "task" or todo.lifecycle_phase != "prepared":
        return False
    if not todo.task_plan_digest:
        return False
    return todo.task_approved_digest != todo.task_plan_digest


def _is_held(todo: TodoItem) -> bool:
    if todo.status in {TodoStatus.ICEBOX, TodoStatus.DELIVERED, TodoStatus.REMOVED}:
        return False
    return todo.held


def _display_kind(kind: str | None) -> str:
    if kind is None:
        return "?"
    return _KIND_DISPLAY.get(kind, kind)


def _col_plain_text(label: str, value: str) -> str:
    """Return the plain text that _build_col would produce for this label/value pair."""
    if not value:
        return ""
    if label:
        return f"{label}:{value}"
    return value


def _work_phase_label(lifecycle_phase: str | None) -> str | None:
    """Look up the W-column phase label for the given lifecycle phase."""
    phase = coerce_lifecycle_phase(lifecycle_phase)
    if phase is None:
        return None
    return _WORK_PHASE_LABELS.get(phase)


_FINALIZE_LABEL_READY = "ready"


def lifecycle_phase_label(phase: str | None, prepare_review_verdict: str | None = None) -> tuple[str, str, str] | None:
    """Return the canonical lifecycle column tuple for a todo, if any.

    A BLOCKED phase carrying a prepare review verdict reads as its actual
    meaning — the reviewed artifact needs a rewrite — instead of a bare
    "blocked" that hides the cause.
    """
    lifecycle_phase = coerce_lifecycle_phase(phase)
    if lifecycle_phase is None:
        return None
    if lifecycle_phase is LifecyclePhase.BLOCKED and prepare_review_verdict:
        return _PHASE_PREFIX_LIFECYCLE, "rewrite", _gold_color()
    value = _LIFECYCLE_PHASE_LABELS.get(lifecycle_phase)
    if not value:
        return None
    color = _ok_color() if is_settled_ok_phase(phase) else _gold_color()
    return _PHASE_PREFIX_LIFECYCLE, value, color


def integration_phase_label(phase: str | None, finalize_status: str | None) -> tuple[str, str, str] | None:
    """Return the integration-phase column tuple for a todo, if any.

    Only two stamped values are recognized: 'started' and 'delivered'.
    Legacy/stale values from the old 12-phase mirror are ignored — todo.py
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

# Cell width reserved for the dedicated state column: a two-dot gap (like every
# other column), the one-cell schedule badge, the 2-cell owner-chip slot, the
# 2-cell autonomous-filing marker slot, and the 2-cell hold glyph slot (last).
# Every row occupies this exact cell width so the right edge aligns.
_SCHEDULE_CELLS = 1
_CHIP_CELLS = 2
_STATE_COL_WIDTH = _COL_GAP + _SCHEDULE_CELLS + _CHIP_CELLS + _AUTONOMOUS_ICON_CELLS + _HOLD_ICON_CELLS

# Horizontal padding from CSS `padding: 0 1` (1 left + 1 right)
_WIDGET_PADDING_HORZ = 2

# Trailing right-gutter reserved on every row at the graceful-degradation floor.
# The narrow-width dot clamp and the final fill/truncate both target this same
# cell count so a clamped column block never bleeds into the reserved gutter
# (which is where the hold glyph's cells would otherwise get truncated away).
_TRAILING_GUTTER_CELLS = 2

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


_KIND_COLORS_DARK: dict[str, str] = {
    "feature": "color(109)",
    "change": "color(141)",
    "bug": "color(160)",
    "task": "color(255)",
}
_KIND_COLORS_LIGHT: dict[str, str] = {
    "feature": "color(66)",
    "change": "color(97)",
    "bug": "color(124)",
    "task": "color(232)",
}


def _kind_color(kind: str | None) -> str:
    """Return the theme-aware color for the kind label."""
    if kind is None:
        return _gold_color()
    colors = _KIND_COLORS_DARK if is_dark_mode() else _KIND_COLORS_LIGHT
    return colors.get(kind or "", colors["feature"])


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
    """Pad a Text to a fixed width with dot leaders.

    Width is measured in display cells (Rich `cell_len`), not `len`, so a column
    containing a wide glyph (the hold icon) reserves the same right edge as an
    ASCII-only column.
    """
    gap = max(0, width - text.cell_len)
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
        # Click sub-regions recorded each render(): the owner-chip cell span (and
        # the email it filters on) and the claimed text-column span.
        self._chip_region: tuple[int, int] | None = None
        self._chip_email: str | None = None
        self._claim_region: tuple[int, int] | None = None
        # Owner chip resolved once per render() and consumed when the chip column
        # is painted; its span is recorded relative to the column block, then
        # offset to an absolute cell range.
        self._render_chip: PersonChip | None = None
        self._render_selected: bool = False
        self._chip_rel_region: tuple[int, int] | None = None
        # The active shared human filter, pushed by the view; the matching
        # person's chip renders inverted.
        self._active_human_filter: str | None = None

    @staticmethod
    def compute_col_widths(todos: list[TodoItem]) -> dict[str, int]:
        """Compute column widths from actual data: max rendered length + gap.

        Column order: K | P (one shared phase slot for P/W/I/T labels) | D
        """
        maxes: dict[str, int] = {"K": 0, "P": 0, "D": 0}
        for t in todos:
            maxes["K"] = max(maxes["K"], len(_col_plain_text(_PHASE_PREFIX_KIND, _display_kind(t.kind))))
            if t.status == TodoStatus.ICEBOX:
                maxes["P"] = max(maxes["P"], len(f"{_PHASE_PREFIX_LIFECYCLE}:icebox"))
                continue
            if _approval_pending(t):
                maxes["P"] = max(maxes["P"], len(f"{_PHASE_PREFIX_LIFECYCLE}:approve"))
                continue
            if t.kind is None:
                maxes["P"] = max(maxes["P"], len(f"{_PHASE_PREFIX_LIFECYCLE}:classify"))
                continue
            work_label = _work_phase_label(t.lifecycle_phase)
            if work_label is not None:
                maxes["P"] = max(maxes["P"], len(f"{_PHASE_PREFIX_WORK}:{work_label}"))
            else:
                p_result = lifecycle_phase_label(t.lifecycle_phase, t.prepare_review_verdict)
                if p_result is not None:
                    p_prefix, p_value, _ = p_result
                    maxes["P"] = max(maxes["P"], len(f"{p_prefix}:{p_value}"))
            i_result = integration_phase_label(t.integration_phase, t.finalize_status)
            if i_result is not None:
                i_prefix, i_value, _ = i_result
                maxes["P"] = max(maxes["P"], len(f"{i_prefix}:{i_value}"))
            if t.deferrals_status:
                maxes["D"] = max(maxes["D"], len(f"D:{t.deferrals_status}"))
        sized = {k: (v + _COL_GAP if v > 0 else 0) for k, v in maxes.items()}
        # Task auth/schedule and the held glyph occupy one dedicated last column,
        # reserved on every row so the right edge aligns. No filler cells: under
        # width compression every cell of block width costs a cell of slug gap.
        sized["_max"] = sized["K"] + sized["P"] + sized["D"] + _STATE_COL_WIDTH
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

    def _claim_style(self) -> Style:
        """Bold overlay for a claimed todo's text columns.

        A claimed todo (a live ``active_runner``) renders its text status columns
        bold; the columns also become a click target that jumps to the runner
        session (the region is recorded in ``render`` and mapped in ``on_click``).
        Empty when unclaimed — text columns then render at normal weight. The row
        status glyph and state icons are styled elsewhere and never bolded by the
        claim.
        """
        if self.todo.active_runner:
            return Style(bold=True)
        return Style()

    def _build_col(self, label: str, value: str, width: int, value_style: Style) -> Text:
        """Render a fixed-width column. Empty value -> blank padding for alignment."""
        col = Text()
        plain = _col_plain_text(label, value)
        claim = self._claim_style()
        if plain:
            prefix_len = len(plain) - len(value)
            if prefix_len:
                col.append(plain[:prefix_len], style=claim)
            col.append(value, style=value_style + claim)
        return _pad(col, width)

    def _total_col_width(self) -> int:
        """Max rendered column width across all paths — the target for uniform padding."""
        return self._col_widths.get("_max", 0)

    def _finish_columns(self, result: Text) -> Text:
        """Dot-pad property columns, then render the fixed-width state column.

        State column, left to right: schedule badge, owner chip, autonomous-
        filing marker, hold glyph (last).
        """
        result = _pad(result, self._total_col_width() - _STATE_COL_WIDTH)
        result.append("·" * _COL_GAP, style=Style(color=_muted_color()))
        if self.todo.schedule:
            result.append("S", style=Style(color=_gold_color(), bold=True))
        else:
            result.append("·", style=Style(color=_muted_color()))
        self._append_chip(result)
        if self.todo.entry_point == "agent" and not self.todo.human_involved:
            result.append(_AUTONOMOUS_ICON, style=Style(color=_muted_color()))
        else:
            result.append("·" * _AUTONOMOUS_ICON_CELLS, style=Style(color=_muted_color()))
        if _is_held(self.todo):
            result.append(_HOLD_ICON, style=Style(color=_gold_color(), bold=True))
        else:
            result.append("·" * _HOLD_ICON_CELLS, style=Style(color=_muted_color()))
        return result

    def _append_chip(self, result: Text) -> None:
        """Paint the owner-chip slot and record its span relative to the column
        block. Blank (dot-filled) when there is no resolvable owner chip."""
        self._chip_rel_region = None
        chip = self._render_chip
        if chip is None:
            result.append("·" * _CHIP_CELLS, style=Style(color=_muted_color()))
            return
        filtered = self._active_human_filter is not None and self._active_human_filter == chip.person_email
        start = result.cell_len
        result.append(chip.initials, style=chip.style(selected=self._render_selected, inverted=filtered))
        self._chip_rel_region = (start, result.cell_len)
        pad = _CHIP_CELLS - len(chip.initials)
        if pad > 0:
            result.append("·" * pad, style=Style(color=_muted_color()))

    def _build_columns(self) -> Text:
        """Build aligned columns. K:<kind> renders first, then phase (P/I) or work (B/R/D)."""
        # Holders show no property columns — status is the projection's leaf
        # aggregate — but still carry the state column (owner chip, hold).
        if self.todo.is_holder:
            return self._finish_columns(Text())

        w = self._col_widths
        result = Text()
        # Kind column renders first on every non-holder row (no colon prefix).
        result.append_text(
            self._build_col(
                _PHASE_PREFIX_KIND,
                _display_kind(self.todo.kind),
                w.get("K", 0),
                Style(color=_kind_color(self.todo.kind)),
            )
        )

        # Icebox items show P:icebox only — no work-phase columns
        if self.todo.status == TodoStatus.ICEBOX:
            result.append_text(
                self._build_col(_PHASE_PREFIX_LIFECYCLE, "icebox", w.get("P", 0), Style(color=_icebox_color()))
            )
            return self._finish_columns(result)

        if _approval_pending(self.todo):
            result.append_text(
                self._build_col(_PHASE_PREFIX_LIFECYCLE, "approve", w.get("P", 0), Style(color=_gold_color()))
            )
            return self._finish_columns(result)

        # Trashed items show T:age only
        if self.todo.status == TodoStatus.REMOVED:
            age = format_relative_time(self.todo.removed_at) if self.todo.removed_at else ""
            result.append_text(self._build_col("T", age, w.get("P", 0), Style(color=_trashed_color())))
            return self._finish_columns(result)

        if self.todo.kind is None:
            result.append_text(
                self._build_col(_PHASE_PREFIX_LIFECYCLE, "classify", w.get("P", 0), Style(color=_gold_color()))
            )
            return self._finish_columns(result)

        ok = _ok_color()
        gold = _gold_color()

        # Phase detection: top-to-bottom, first match wins. All lanes share one
        # phase column slot (I/W/P labels); only D renders beside it.

        # 1. Active or queued integration phase — outranks work labels so a
        # handed-off or delivered row never masks as W:finalize.
        i_result = integration_phase_label(self.todo.integration_phase, self.todo.finalize_status)
        if i_result is not None:
            i_label, i_value, i_color = i_result
            if self.todo.integration_phase == "delivered":
                i_value = format_relative_time(self.todo.delivered_at) if self.todo.delivered_at else ""
            result.append_text(self._build_col(i_label, i_value, w.get("P", 0), Style(color=i_color)))
            return self._finish_columns(result)

        # 2. Work phase — one W label carries the whole build/review/fix story.
        work_label = _work_phase_label(self.todo.lifecycle_phase)
        if work_label is not None:
            color = ok if is_settled_ok_phase(self.todo.lifecycle_phase) else gold
            result.append_text(self._build_col(_PHASE_PREFIX_WORK, work_label, w.get("P", 0), Style(color=color)))
            ds = self.todo.deferrals_status
            result.append_text(self._build_col("D", ds or "", w.get("D", 0), _DIM))
            return self._finish_columns(result)

        # 3. Active prepare lifecycle phase
        p_result = lifecycle_phase_label(self.todo.lifecycle_phase, self.todo.prepare_review_verdict)
        if p_result is not None:
            p_label, p_value, p_color = p_result
            result.append_text(self._build_col(p_label, p_value, w.get("P", 0), Style(color=p_color)))
            return self._finish_columns(result)

        # 4. Ready/pending state — no phase/work columns
        return self._finish_columns(result)

    def _slug_render(self, shared_start: int, prefix_width: int) -> tuple[str, int]:
        """Return the full slug and its dot-leader count for this row.

        The slug is the row's identity and is never truncated. The dot run pads
        to the shared column start when the slug fits under it; a slug longer
        than the shared budget keeps the minimum column gap instead, pushing
        only its own row's columns to the right.
        """
        slug = self.todo.slug
        dot_count = max(_COL_GAP, shared_start - prefix_width - len(slug))
        return slug, dot_count

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

        # The owner chip lives in its own state column (schedule badge, owner
        # chip, autonomous-filing marker, hold glyph); resolve it once here and
        # paint it in _finish_columns. The slug starts immediately after the
        # status glyph. Resolved from the lineage root — never the whole
        # chain, which would fail principal_to_email.
        self._render_chip = resolve_person_chip(Lineage.root_of(self.todo.lineage))
        self._render_selected = is_selected
        self._chip_region = None
        self._chip_email = None

        if is_selected:
            slug_style = Style(reverse=True)
        else:
            slug_style = Style()
        # Column geometry: the property-column block always starts at a shared
        # cell offset derived only from the shared inputs (slug_width, max_depth,
        # col_widths) - never from this row's own slug length - so every row's
        # columns and state column align regardless of tree depth or slug length.
        outer_w = self.outer_size.width
        available = outer_w - _WIDGET_PADDING_HORZ if outer_w > 0 else 0
        prefix_width = 2 + len(self._tree_lines) * 2 + 2 + 1 + 1  # "  " + tree + "├─" + icon + " "
        if outer_w > 0:
            # Self-organizing layout with two invariants: the slug is never
            # truncated, and the property columns stay on the pane. The shared
            # column start prefers the longest-slug position; when the pane
            # cannot fit that plus the column block, it compresses so the
            # columns fit — but never below this row's own slug plus the
            # minimum gap, so a long-slug row pushes only its own columns
            # toward the edge instead of losing its identity.
            ideal_start = 8 + self._slug_width + 2 * self._max_depth
            fit_start = available - _TRAILING_GUTTER_CELLS - self._total_col_width()
            floor_start = 8 + 2 * self._max_depth
            shared_start = min(ideal_start, max(floor_start, fit_start))
            display_slug, dot_count = self._slug_render(shared_start, prefix_width)
        else:
            indent_compensation = (self._max_depth - len(self._tree_lines)) * 2
            display_slug = self.todo.slug
            dot_count = max(1, self._slug_width - len(display_slug) + 2 + indent_compensation)

        line.append(display_slug, style=slug_style)
        line.append("\u00b7" * dot_count, style=Style(color=_muted_color()))

        # Property columns, including the dedicated held column as the block's last
        # column (the hold glyph or its reserved blank slot). When the todo is
        # claimed, the text columns (up to but excluding the state-icon column)
        # become the jump-to-runner click region.
        columns_start = line.cell_len
        line.append_text(self._build_columns())
        if self._chip_rel_region is not None and self._render_chip is not None:
            rel_start, rel_end = self._chip_rel_region
            self._chip_region = (columns_start + rel_start, columns_start + rel_end)
            self._chip_email = self._render_chip.person_email
        if self.todo.active_runner:
            text_columns_end = columns_start + max(0, self._total_col_width() - _STATE_COL_WIDTH)
            self._claim_region = (columns_start, text_columns_end)
        else:
            self._claim_region = None

        # Fill to the current window width, reserving exactly _TRAILING_GUTTER_CELLS
        # trailing spaces (not dots) as the right gutter. Responsive to the live
        # pane width. Cell width (not len) drives the gap so the wide hold glyph
        # does not drift.
        if outer_w > 0:
            fill_to = max(0, available - _TRAILING_GUTTER_CELLS)
            gap = fill_to - line.cell_len
            if gap > 0:
                line.append("·" * gap, style=Style(color=_muted_color()))
            line.truncate(fill_to)
            line.append("  ")

        return line

    def _click_column(self, event: Click) -> int | None:
        """Return the content column of a click, or None when unavailable."""
        offset = event.style.meta.get(_CLICK_OFFSET_META) if event.style else None
        if isinstance(offset, tuple) and len(offset) == 2:
            return int(offset[0])
        return None

    def on_click(self, event: Click) -> None:
        """Route a click to a jump, a filter, or row selection by its column.

        A click on a claimed todo's text columns jumps to the runner session; a
        click on the owner chip toggles the shared human filter; any other click
        selects the row.
        """
        event.stop()
        column = self._click_column(event)
        if column is not None:
            if (
                self.todo.active_runner
                and self._claim_region
                and self._claim_region[0] <= column < self._claim_region[1]
            ):
                self.post_message(JumpToSession(str(self.todo.active_runner)))
                return
            if self._chip_email and self._chip_region and self._chip_region[0] <= column < self._chip_region[1]:
                self.post_message(ChipFilterToggle(self._chip_email))
                return
        self.post_message(self.Pressed(self))
