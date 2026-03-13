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
from teleclaude.core.integration.state_machine import IntegrationPhase
from teleclaude.core.next_machine.core import DOR_READY_THRESHOLD, PreparePhase

_CONNECTOR = Style(color=CONNECTOR_COLOR)
_DIM = Style(dim=True)

_PHASE_PREFIX_PREPARE = "P"
_PHASE_PREFIX_INTEGRATION = "I"

_PREPARE_LABEL_DISCOVERY = "discovery"
_PREPARE_LABEL_REQUIREMENTS = "requirements"
_PREPARE_LABEL_PLANNING = "planning"
_PREPARE_LABEL_BLOCKED = "blocked"

_INTEGRATION_LABEL_STARTED = "started"
_INTEGRATION_LABEL_DELIVERED = "delivered"
_INTEGRATION_LABEL_FAILED = "failed"
_INTEGRATION_LABEL_QUEUED = "queued"

_TODO_STATUS_DRAFT = "draft"
_TODO_STATUS_READY = "ready"
_TODO_STATUS_ACTIVE = "active"
_TODO_STATUS_PENDING = "pending"
_TODO_STATUS_COMPLETE = "complete"
_TODO_STATUS_APPROVED = "approved"

_PREPARE_PHASE_LABELS: dict[PreparePhase, str] = {
    PreparePhase.INPUT_ASSESSMENT: _PREPARE_LABEL_DISCOVERY,
    PreparePhase.TRIANGULATION: _PREPARE_LABEL_DISCOVERY,
    PreparePhase.REQUIREMENTS_REVIEW: _PREPARE_LABEL_REQUIREMENTS,
    PreparePhase.PLAN_DRAFTING: _PREPARE_LABEL_PLANNING,
    PreparePhase.PLAN_REVIEW: _PREPARE_LABEL_PLANNING,
    PreparePhase.GATE: _PREPARE_LABEL_PLANNING,
    PreparePhase.GROUNDING_CHECK: _PREPARE_LABEL_PLANNING,
    PreparePhase.RE_GROUNDING: _PREPARE_LABEL_PLANNING,
    PreparePhase.BLOCKED: _PREPARE_LABEL_BLOCKED,
}

_FINALIZE_LABEL_QUEUED = "handed_off"
_INTEGRATION_CLEARANCE_PHASE = "clearance_wait"

_INTEGRATION_STARTED_PHASES: frozenset[str] = frozenset(
    {
        IntegrationPhase.CANDIDATE_DEQUEUED.value,
        _INTEGRATION_CLEARANCE_PHASE,
        IntegrationPhase.MERGE_CLEAN.value,
        IntegrationPhase.MERGE_CONFLICTED.value,
        IntegrationPhase.AWAITING_COMMIT.value,
        IntegrationPhase.COMMITTED.value,
        IntegrationPhase.DELIVERY_BOOKKEEPING.value,
    }
)

_INTEGRATION_DELIVERED_PHASES: frozenset[str] = frozenset(
    {
        IntegrationPhase.PUSH_SUCCEEDED.value,
        IntegrationPhase.CLEANUP.value,
        IntegrationPhase.CANDIDATE_DELIVERED.value,
        IntegrationPhase.COMPLETED.value,
    }
)


def _coerce_prepare_phase(phase: str | None) -> PreparePhase | None:
    if not phase:
        return None
    try:
        return PreparePhase(phase)
    except ValueError:
        return None


def prepare_phase_label(phase: str | None) -> tuple[str, str, str] | None:
    prepared_phase = _coerce_prepare_phase(phase)
    if not prepared_phase:
        return None
    value = _PREPARE_PHASE_LABELS.get(prepared_phase)
    if not value:
        return None
    color = _gold_color() if prepared_phase == PreparePhase.BLOCKED else _ok_color()
    return _PHASE_PREFIX_PREPARE, value, color


def integration_phase_label(phase: str | None, finalize_status: str | None) -> tuple[str, str, str] | None:
    if phase in _INTEGRATION_STARTED_PHASES:
        return _PHASE_PREFIX_INTEGRATION, _INTEGRATION_LABEL_STARTED, _ok_color()
    if phase in _INTEGRATION_DELIVERED_PHASES:
        return _PHASE_PREFIX_INTEGRATION, _INTEGRATION_LABEL_DELIVERED, _ok_color()
    if phase == IntegrationPhase.PUSH_REJECTED.value:
        return _PHASE_PREFIX_INTEGRATION, _INTEGRATION_LABEL_FAILED, _gold_color()
    if not phase:
        if finalize_status == _FINALIZE_LABEL_QUEUED:
            return _PHASE_PREFIX_INTEGRATION, _INTEGRATION_LABEL_QUEUED, _ok_color()
        return None

    return None


# Status colors: dark/light table (like agent colors)
_STATUS_COLORS_DARK = {
    _TODO_STATUS_DRAFT: "color(244)",
    _TODO_STATUS_READY: "color(71)",
    _TODO_STATUS_ACTIVE: "color(178)",
}
_STATUS_COLORS_LIGHT = {
    _TODO_STATUS_DRAFT: "color(244)",
    _TODO_STATUS_READY: "color(28)",
    _TODO_STATUS_ACTIVE: "color(136)",
}

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

        Column order: P | I | DOR | B | R | F | D
        """
        maxes: dict[str, int] = {"P": 0, "I": 0, "DOR": 0, "B": 0, "R": 0, "F": 0, "D": 0}
        for t in todos:
            p_result = prepare_phase_label(t.prepare_phase)
            if p_result is not None:
                p_prefix, p_value, _ = p_result
                maxes["P"] = max(maxes["P"], len(f"{p_prefix}:{p_value}"))
            i_result = integration_phase_label(t.integration_phase, t.finalize_status)
            if i_result is not None:
                i_prefix, i_value, _ = i_result
                maxes["I"] = max(maxes["I"], len(f"{i_prefix}:{i_value}"))
            if t.dor_score is not None:
                maxes["DOR"] = max(maxes["DOR"], len(f"DOR:{t.dor_score}"))
            bs = t.build_status
            if bs and bs != _TODO_STATUS_PENDING:
                maxes["B"] = max(maxes["B"], len(f"B:{bs}"))
            rs = t.review_status
            if rs and rs != _TODO_STATUS_PENDING:
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

    def _build_columns(self) -> Text:
        """Build aligned property columns. Phase-aware: P | I take priority over B/R/F/D."""
        result = Text()
        ok = _ok_color()
        gold = _gold_color()
        w = self._col_widths

        # DOR column (shown alongside P; also shown in work phase)
        dor = self.todo.dor_score
        dor_color = ok if dor is not None and dor >= DOR_READY_THRESHOLD else gold
        dor_text = self._build_col("DOR", str(dor) if dor is not None else "", w.get("DOR", 0), Style(color=dor_color))

        # Phase detection: top-to-bottom, first match wins.

        # 1. Active prepare phase
        p_result = prepare_phase_label(self.todo.prepare_phase)
        if p_result is not None:
            p_label, p_value, p_color = p_result
            result.append_text(dor_text)
            result.append_text(self._build_col(p_label, p_value, w.get("P", 0), Style(color=p_color, bold=True)))
            return result

        # 2. Active or queued integration phase
        i_result = integration_phase_label(self.todo.integration_phase, self.todo.finalize_status)
        if i_result is not None:
            i_label, i_value, i_color = i_result
            result.append_text(self._build_col(i_label, i_value, w.get("I", 0), Style(color=i_color, bold=True)))
            return result

        # 3. Work phase (build != pending) — existing B/R/F/D path
        bs = self.todo.build_status
        if bs is not None and bs != _TODO_STATUS_PENDING:
            result.append_text(dor_text)

            b_val = bs if bs and bs != _TODO_STATUS_PENDING else ""
            result.append_text(
                self._build_col(
                    "B", b_val, w.get("B", 0), Style(color=ok if bs == _TODO_STATUS_COMPLETE else gold, bold=True)
                )
            )

            rs = self.todo.review_status
            r_val = rs if rs and rs != _TODO_STATUS_PENDING else ""
            result.append_text(
                self._build_col(
                    "R", r_val, w.get("R", 0), Style(color=ok if rs == _TODO_STATUS_APPROVED else gold, bold=True)
                )
            )

            fc = self.todo.findings_count
            result.append_text(self._build_col("F", str(fc) if fc else "", w.get("F", 0), Style(color=gold, bold=True)))

            ds = self.todo.deferrals_status
            result.append_text(self._build_col("D", ds or "", w.get("D", 0), _DIM))

            return result

        # 4. Ready/pending state — DOR only
        result.append_text(dor_text)
        return result

    def render(self) -> Text:
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
        else:
            line.append("\u25a0", style=self._status_style())
        line.append(" ")

        # Slug — muted when required planning artifacts are missing.
        # Bug items intentionally use bug.md instead of requirements/plan.
        is_bug = any(name.lower() == "bug.md" for name in self.todo.files)
        missing_artifacts = not is_bug and (not self.todo.has_requirements or not self.todo.has_impl_plan)
        if is_selected:
            slug_style = Style(reverse=True)
        elif missing_artifacts:
            slug_style = Style(color=_muted_color())
        else:
            slug_style = Style()
        line.append(self.todo.slug, style=slug_style)

        # Dot padding from slug to columns (compensate for indent so columns align)
        indent_compensation = (self._max_depth - len(self._tree_lines)) * 2
        dot_count = max(1, self._slug_width - len(self.todo.slug) + 2 + indent_compensation)
        line.append("\u00b7" * dot_count, style=Style(color=_muted_color()))

        # Property columns (DOR first)
        line.append_text(self._build_columns())

        return line

    def on_click(self, event: Click) -> None:
        """Post Pressed message when clicked."""
        event.stop()
        self.post_message(self.Pressed(self))
