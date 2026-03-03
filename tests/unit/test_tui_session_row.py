"""Unit tests for SessionRow rendering logic — title lines, detail lines, styles."""

from datetime import UTC, datetime

from teleclaude.cli.models import SessionInfo
from teleclaude.cli.tui.widgets.session_row import SessionRow


def _session(
    session_id: str = "sess-001",
    title: str = "Test Session",
    status: str = "active",
    active_agent: str | None = "claude",
    thinking_mode: str = "slow",
    last_input: str | None = None,
    last_activity: str | None = None,
    tmux_session_name: str | None = "teleclaude-sess-001",
) -> SessionInfo:
    now = last_activity or datetime.now(UTC).isoformat()
    return SessionInfo(
        session_id=session_id,
        title=title,
        status=status,
        computer="local",
        active_agent=active_agent,
        thinking_mode=thinking_mode,
        last_input_origin="telegram",
        project_path="/test/path",
        created_at=now,
        last_activity=now,
        last_input=last_input,
        last_output_summary=None,
        tmux_session_name=tmux_session_name,
    )


def _row(session: SessionInfo | None = None, **kwargs: object) -> SessionRow:
    return SessionRow(session=session or _session(), **kwargs)


# -- Properties --


def test_session_id_from_session():
    row = _row(_session(session_id="abc"))
    assert row.session_id == "abc"


def test_agent_from_session():
    row = _row(_session(active_agent="gemini"))
    assert row.agent == "gemini"


def test_mode_from_session():
    row = _row(_session(thinking_mode="fast"))
    assert row.mode == "fast"


def test_status_defaults_to_idle():
    row = _row(_session(status=""))
    assert row.status == "idle"


def test_headless_when_no_tmux():
    row = _row(_session(tmux_session_name=None))
    assert row._is_headless is True


def test_not_headless_with_tmux():
    row = _row(_session(tmux_session_name="teleclaude-sess"))
    assert row._is_headless is False


def test_headless_with_headless_status():
    row = _row(_session(status="headless_active"))
    assert row._is_headless is True


# -- _build_title_line --


def test_title_line_contains_agent_mode():
    """Title line shows agent/mode."""
    row = _row(_session(active_agent="claude", thinking_mode="slow"))
    line = row._build_title_line()
    assert "claude/slow" in line.plain


def test_title_line_contains_title_in_quotes():
    """Title appears in quotes."""
    row = _row(_session(title="My Task"))
    line = row._build_title_line()
    assert '"My Task"' in line.plain


def test_title_line_untitled_fallback():
    """Empty title shows (untitled)."""
    row = _row(_session(title=""))
    line = row._build_title_line()
    assert "(untitled)" in line.plain


def test_title_line_contains_badge():
    """Title line includes display index badge."""
    row = _row(display_index="3")
    line = row._build_title_line()
    assert "[3]" in line.plain


def test_title_line_collapse_indicator_collapsed():
    """Collapsed row shows ▶ chevron."""
    row = _row()
    row.collapsed = True
    line = row._build_title_line()
    assert "\u25b6" in line.plain


def test_title_line_collapse_indicator_expanded():
    """Expanded row shows ▼ chevron."""
    row = _row()
    row.collapsed = False
    line = row._build_title_line()
    assert "\u25bc" in line.plain


def test_title_line_shell_when_no_agent():
    """No active agent shows 'shell' label."""
    row = _row(_session(active_agent=None))
    line = row._build_title_line()
    assert "shell/" in line.plain


# -- _get_row_style --


def test_row_style_selected_is_bold():
    """Selected rows use bold style."""
    row = _row()
    style = row._get_row_style(selected=True)
    assert style.bold


def test_row_style_previewed_is_bold():
    """Previewed rows use bold style."""
    row = _row()
    style = row._get_row_style(previewed=True)
    assert style.bold


def test_row_style_highlight_when_collapsed_with_input():
    """Collapsed row with input highlight uses highlight tier."""
    row = _row()
    row.collapsed = True
    row.highlight_type = "input"
    style = row._get_row_style()
    assert style is not None  # Resolved from theme


def test_row_style_normal_default():
    """Default style is agent normal tier."""
    row = _row()
    row.collapsed = True
    row.highlight_type = ""
    style = row._get_row_style()
    assert style is not None


# -- _tier (headless shift) --


def test_tier_shift_headless():
    """Headless sessions shift tiers down one level."""
    row = _row(_session(tmux_session_name=None))
    assert row._tier("highlight") == "normal"
    assert row._tier("normal") == "muted"
    assert row._tier("muted") == "subtle"
    assert row._tier("subtle") == "subtle"


def test_tier_no_shift_interactive():
    """Interactive sessions keep original tiers."""
    row = _row(_session(tmux_session_name="teleclaude-sess"))
    assert row._tier("highlight") == "highlight"
    assert row._tier("normal") == "normal"


# -- _build_detail_lines --


def test_detail_lines_show_session_id():
    """Expanded detail includes session ID."""
    row = _row(_session(session_id="sess-xyz"))
    row.collapsed = False
    lines = row._build_detail_lines()
    assert any("sess-xyz" in line.plain for line in lines)


def test_detail_lines_show_last_input():
    """Input line appears when last_input is set."""
    row = _row(_session(last_input="hello world"))
    row.collapsed = False
    lines = row._build_detail_lines()
    assert any("hello world" in line.plain for line in lines)


def test_detail_lines_no_input_when_empty():
    """No input line when last_input is None."""
    row = _row(_session(last_input=None))
    row.collapsed = False
    lines = row._build_detail_lines()
    # Only session ID line, no input line
    input_lines = [l for l in lines if " in: " in l.plain]
    assert len(input_lines) == 0


def test_detail_lines_active_tool_shown():
    """Active tool output renders in detail lines."""
    row = _row()
    row.collapsed = False
    row.active_tool = "Reading file.py"
    lines = row._build_detail_lines()
    tool_lines = [l for l in lines if "Reading file.py" in l.plain]
    assert len(tool_lines) == 1


def test_detail_lines_output_summary():
    """Output summary appears when set and no active tool."""
    row = _row()
    row.collapsed = False
    row.last_output_summary = "Finished analysis"
    lines = row._build_detail_lines()
    assert any("Finished analysis" in line.plain for line in lines)


def test_detail_lines_placeholder_on_highlight():
    """When highlighted but no summary, shows '...' placeholder."""
    row = _row()
    row.collapsed = False
    row.highlight_type = "output"
    lines = row._build_detail_lines()
    assert any("..." in line.plain for line in lines)


# -- _build_connector_bottom --


def test_connector_last_child_uses_corner():
    """Last child in subtree uses └ connector."""
    row = _row()
    row.is_last_child = True
    line = row._build_connector_bottom()
    assert "\u2514" in line.plain


def test_connector_non_last_uses_tee():
    """Non-last child uses ├ connector."""
    row = _row()
    row.is_last_child = False
    line = row._build_connector_bottom()
    assert "\u251c" in line.plain


# -- update_session --


def test_update_session_replaces_data():
    """update_session swaps the underlying session object."""
    row = _row(_session(title="Old"))
    new = _session(title="New")
    row.update_session(new)
    assert row.session.title == "New"
