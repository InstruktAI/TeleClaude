"""Unit tests for TodoRow rendering logic — column alignment, status badges, styling."""

from unittest.mock import patch

from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.widgets.todo_row import TodoRow


def _todo(
    slug: str = "my-task",
    status: TodoStatus = TodoStatus.PENDING,
    dor_score: int | None = None,
    build_status: str | None = None,
    review_status: str | None = None,
    findings_count: int = 0,
    deferrals_status: str | None = None,
    has_requirements: bool = True,
    has_impl_plan: bool = True,
    files: list[str] | None = None,
) -> TodoItem:
    return TodoItem(
        slug=slug,
        status=status,
        description=None,
        has_requirements=has_requirements,
        has_impl_plan=has_impl_plan,
        build_status=build_status,
        review_status=review_status,
        dor_score=dor_score,
        deferrals_status=deferrals_status,
        findings_count=findings_count,
        files=files or [],
    )


# -- compute_col_widths --


def test_col_widths_empty():
    """No todos produces all-zero widths."""
    assert TodoRow.compute_col_widths([]) == {"DOR": 0, "B": 0, "R": 0, "F": 0, "D": 0}


def test_col_widths_with_dor():
    """DOR column width is derived from the widest score."""
    todos = [_todo(dor_score=8), _todo(dor_score=10)]
    w = TodoRow.compute_col_widths(todos)
    # "DOR:10" = 6 chars + 2 gap = 8
    assert w["DOR"] == len("DOR:10") + 2


def test_col_widths_pending_build_ignored():
    """build_status='pending' doesn't contribute to column width."""
    todos = [_todo(build_status="pending")]
    w = TodoRow.compute_col_widths(todos)
    assert w["B"] == 0


def test_col_widths_active_build():
    """Non-pending build_status contributes to B column."""
    todos = [_todo(build_status="started")]
    w = TodoRow.compute_col_widths(todos)
    assert w["B"] == len("B:started") + 2


def test_col_widths_findings():
    """Findings count contributes to F column."""
    todos = [_todo(findings_count=3)]
    w = TodoRow.compute_col_widths(todos)
    assert w["F"] == len("F:3") + 2


def test_col_widths_deferrals():
    """Deferrals status contributes to D column."""
    todos = [_todo(deferrals_status="2/3")]
    w = TodoRow.compute_col_widths(todos)
    assert w["D"] == len("D:2/3") + 2


# -- _status_style --


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_draft_status_style_dark(_mock):
    """Draft status uses gray color in dark mode."""
    row = TodoRow(_todo(status=TodoStatus.PENDING))
    style = row._status_style()
    assert style.color is not None
    assert not style.bold


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_ready_status_style_dark(_mock):
    """Ready status uses green color in dark mode."""
    row = TodoRow(_todo(status=TodoStatus.READY))
    style = row._status_style()
    assert style.color is not None
    assert not style.bold


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_active_status_style_bold_dark(_mock):
    """Active status is bold in dark mode."""
    row = TodoRow(_todo(status=TodoStatus.IN_PROGRESS))
    style = row._status_style()
    assert style.bold


# -- _build_columns --


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_build_columns_empty_when_no_data(_mock):
    """Columns with no data produce empty text (just padding)."""
    row = TodoRow(_todo(), col_widths={"DOR": 0, "B": 0, "R": 0, "F": 0, "D": 0})
    cols = row._build_columns()
    assert cols.plain == ""


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_build_columns_shows_dor(_mock):
    """DOR column renders with score value."""
    widths = {"DOR": 8, "B": 0, "R": 0, "F": 0, "D": 0}
    row = TodoRow(_todo(dor_score=8), col_widths=widths)
    cols = row._build_columns()
    assert "DOR:" in cols.plain
    assert "8" in cols.plain


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_build_columns_shows_build_and_review(_mock):
    """B and R columns render when non-pending."""
    widths = {"DOR": 0, "B": 12, "R": 12, "F": 0, "D": 0}
    row = TodoRow(_todo(build_status="started", review_status="approved"), col_widths=widths)
    cols = row._build_columns()
    assert "B:started" in cols.plain
    assert "R:approved" in cols.plain


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_build_columns_skips_pending_build(_mock):
    """Pending build status renders as empty column."""
    widths = {"DOR": 0, "B": 12, "R": 0, "F": 0, "D": 0}
    row = TodoRow(_todo(build_status="pending"), col_widths=widths)
    cols = row._build_columns()
    assert "B:" not in cols.plain


# -- render (tree prefix and slug) --


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_render_contains_slug(_mock):
    """Rendered output contains the todo slug."""
    row = TodoRow(_todo(slug="my-feature"), slug_width=20, col_widths={"DOR": 0, "B": 0, "R": 0, "F": 0, "D": 0})
    text = row.render()
    assert "my-feature" in text.plain


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_render_last_child_uses_corner_connector(_mock):
    """Last child in tree uses └─ connector."""
    row = TodoRow(_todo(), is_last=True, col_widths={"DOR": 0, "B": 0, "R": 0, "F": 0, "D": 0})
    text = row.render()
    assert "\u2514" in text.plain  # └


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_render_non_last_uses_tee_connector(_mock):
    """Non-last child in tree uses ├─ connector."""
    row = TodoRow(_todo(), is_last=False, col_widths={"DOR": 0, "B": 0, "R": 0, "F": 0, "D": 0})
    text = row.render()
    assert "\u251c" in text.plain  # ├


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_render_draft_uses_open_square(_mock):
    """Draft status shows □ (open square)."""
    row = TodoRow(_todo(status=TodoStatus.PENDING), col_widths={"DOR": 0, "B": 0, "R": 0, "F": 0, "D": 0})
    text = row.render()
    assert "\u25a1" in text.plain  # □


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_render_ready_uses_filled_square(_mock):
    """Ready status shows ■ (filled square)."""
    row = TodoRow(_todo(status=TodoStatus.READY), col_widths={"DOR": 0, "B": 0, "R": 0, "F": 0, "D": 0})
    text = row.render()
    assert "\u25a0" in text.plain  # ■


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_render_missing_artifacts_mutes_slug(_mock):
    """Missing requirements or impl_plan mutes the slug color."""
    row = TodoRow(
        _todo(has_requirements=False, has_impl_plan=True),
        col_widths={"DOR": 0, "B": 0, "R": 0, "F": 0, "D": 0},
    )
    text = row.render()
    # Find the slug span and check it has a style applied
    slug_start = text.plain.index("my-task")
    spans_at_slug = [s for s in text._spans if s.start <= slug_start < s.end]
    assert any(s.style.color is not None for s in spans_at_slug)


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_render_bug_item_not_muted_without_requirements(_mock):
    """Bug items (have bug.md) are not muted even without requirements/plan."""
    row = TodoRow(
        _todo(has_requirements=False, has_impl_plan=False, files=["bug.md"]),
        col_widths={"DOR": 0, "B": 0, "R": 0, "F": 0, "D": 0},
    )
    text = row.render()
    slug_start = text.plain.index("my-task")
    spans_at_slug = [s for s in text._spans if s.start <= slug_start < s.end]
    # Bug items should use default style (no muted color)
    muted_styles = [s for s in spans_at_slug if s.style.color is not None and "244" in str(s.style.color)]
    assert len(muted_styles) == 0


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_render_tree_lines_continuation(_mock):
    """Tree continuation lines (│) rendered for ancestor depth."""
    row = TodoRow(
        _todo(),
        tree_lines=[True, False],
        col_widths={"DOR": 0, "B": 0, "R": 0, "F": 0, "D": 0},
    )
    text = row.render()
    # First ancestor continues (│), second doesn't (space)
    assert "\u2502" in text.plain
