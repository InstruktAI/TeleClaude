"""Unit tests for TmuxPaneManager."""

import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.cli.tui import theme
from teleclaude.cli.tui.pane_manager import ComputerInfo, TmuxPaneManager


def test_toggle_session_returns_false_when_not_in_tmux():
    """Test that toggle_session returns False when not running inside tmux."""
    with patch.dict(os.environ):
        os.environ.pop("TMUX", None)
        manager = TmuxPaneManager()
        result = manager.toggle_session("session-1", "claude")

    assert result is False
    assert manager.active_session is None


def test_show_session_tracks_active_pane():
    """Test that show_session sets pane and session state when pane is created."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    mock_run = Mock(return_value="%5")
    with patch.object(manager, "_run_tmux", mock_run):
        manager.show_session(
            "parent-session",
            "claude",
            computer_info=ComputerInfo(name="local", is_local=True),
        )

    assert manager.state.active_session_id is not None
    assert manager._active_pane_id is not None
    # Verify at least one split-window command issued
    assert any(call.args[0] == "split-window" for call in mock_run.call_args_list)


def test_toggle_session_hides_when_already_showing():
    """Test that toggle_session hides panes when toggling the current session."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    # Simulate active session via catalog + state
    manager._session_catalog = {
        "sid-1": SimpleNamespace(session_id="sid-1", tmux_session_name="session-1", active_agent="claude")
    }
    manager.state.active_session_id = "sid-1"
    with patch.object(manager, "_render_layout", return_value=None):
        result = manager.toggle_session("session-1", "claude")

    assert result is False
    assert manager.active_session is None


def test_hide_sessions_kills_existing_panes_and_clears_state():
    """Test that hide_sessions cleans up panes and resets state."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    manager.state.session_to_pane["sid-1"] = "%10"
    manager.state.active_session_id = "sid-1"

    mock_run = Mock(return_value="")
    with patch.object(manager, "_run_tmux", mock_run), patch.object(manager, "_get_pane_exists", return_value=True):
        manager.hide_sessions()

    assert manager.state.active_session_id is None
    assert manager.active_session is None
    # Verify kill-pane command issued for active pane
    assert ("kill-pane", "-t", "%10") in [call.args for call in mock_run.call_args_list]


def test_set_pane_background_overrides_only_at_paint_theming_level():
    """Session panes get agent fg+bg only when paint theming is active (level 3)."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    mock_run = Mock(return_value="")
    with (
        patch.object(manager, "_run_tmux", mock_run),
        patch.object(theme, "should_apply_paint_pane_theming", return_value=True),
        patch.object(theme, "get_agent_pane_inactive_background", return_value="#101010"),
        patch.object(theme, "get_agent_pane_active_background", return_value="#000000"),
        patch.object(theme, "get_agent_normal_color", return_value=222),
    ):
        manager._set_pane_background("%9", "tc_test", "claude")

    style_calls = [call.args for call in mock_run.call_args_list if call.args[:4] == ("set", "-p", "-t", "%9")]
    assert ("set", "-p", "-t", "%9", "window-style", "fg=colour222,bg=#101010") in style_calls
    assert ("set", "-p", "-t", "%9", "window-active-style", "fg=colour222,bg=#000000") in style_calls


def test_set_pane_background_native_when_paint_theming_off():
    """Session panes use native defaults when paint theming is off."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    mock_run = Mock(return_value="")
    with (
        patch.object(manager, "_run_tmux", mock_run),
        patch.object(theme, "should_apply_paint_pane_theming", return_value=False),
    ):
        manager._set_pane_background("%9", "tc_test", "claude")

    style_calls = [call.args for call in mock_run.call_args_list]
    assert ("set", "-pu", "-t", "%9", "window-style") in style_calls
    assert ("set", "-pu", "-t", "%9", "window-active-style") in style_calls


def test_set_pane_background_uses_selected_haze_for_tree_selection():
    """Selected tree sessions should use the lighter tree selection haze when paint theming is on."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    mock_run = Mock(return_value="")
    with (
        patch.object(manager, "_run_tmux", mock_run),
        patch.object(theme, "should_apply_paint_pane_theming", return_value=True),
        patch.object(theme, "get_agent_pane_inactive_background", return_value="#101010"),
        patch.object(theme, "get_agent_pane_selected_background", return_value="#060606") as get_selected,
        patch.object(theme, "get_agent_pane_active_background", return_value="#000000"),
        patch.object(theme, "get_agent_normal_color", return_value=222),
    ):
        manager._set_pane_background("%9", "tc_test", "claude", is_tree_selected=True)

    style_calls = [call.args for call in mock_run.call_args_list if call.args[:4] == ("set", "-p", "-t", "%9")]
    assert ("set", "-p", "-t", "%9", "window-style", "fg=colour222,bg=#060606") in style_calls
    assert get_selected.call_count == 1


def test_doc_pane_background_is_applied_for_non_session_specs():
    """Doc/preview panes should get explicit neutral styles."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    mock_run = Mock(return_value="")
    with (
        patch.object(manager, "_run_tmux", mock_run),
        patch.object(theme, "should_apply_paint_pane_theming", return_value=False),
        patch.object(theme, "get_tui_inactive_background", return_value="#e8e2d0"),
        patch.object(theme, "get_terminal_background", return_value="#fdf6e3"),
    ):
        manager._set_doc_pane_background("%42")

    style_calls = [call.args for call in mock_run.call_args_list]
    assert ("set", "-pu", "-t", "%42", "window-style") in style_calls
    assert ("set", "-pu", "-t", "%42", "window-active-style") in style_calls


def test_doc_pane_background_is_tinted_when_paint_theming_is_enabled():
    """Doc/preview panes should use agent colors in paint-theming mode."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    mock_run = Mock(return_value="")
    with (
        patch.object(manager, "_run_tmux", mock_run),
        patch.object(theme, "should_apply_paint_pane_theming", return_value=True),
        patch.object(theme, "get_tui_inactive_background", return_value="#e8e2d0"),
        patch.object(theme, "get_terminal_background", return_value="#fdf6e3"),
        patch.object(theme, "get_agent_normal_color", return_value=222),
    ):
        manager._set_doc_pane_background("%42", agent="claude")

    style_calls = [call.args for call in mock_run.call_args_list if call.args[:4] == ("set", "-p", "-t", "%42")]
    assert ("set", "-p", "-t", "%42", "window-style", "fg=colour222,bg=#e8e2d0") in style_calls
    assert ("set", "-p", "-t", "%42", "window-active-style", "fg=colour222,bg=#fdf6e3") in style_calls


def test_doc_pane_background_uses_native_foreground_for_anonymous_paints_in_theming_mode():
    """Doc/paint panes without explicit agent should keep native fg even when paint theming is on."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    mock_run = Mock(return_value="")
    with (
        patch.object(manager, "_run_tmux", mock_run),
        patch.object(theme, "should_apply_paint_pane_theming", return_value=True),
        patch.object(theme, "get_tui_inactive_background", return_value="#e8e2d0"),
        patch.object(theme, "get_terminal_background", return_value="#fdf6e3"),
        patch.object(theme, "get_agent_normal_color", return_value=222),
    ):
        manager._set_doc_pane_background("%42")

    style_calls = [call.args for call in mock_run.call_args_list if call.args[:4] == ("set", "-p", "-t", "%42")]
    assert ("set", "-p", "-t", "%42", "window-style", "bg=#e8e2d0") in style_calls
    assert ("set", "-p", "-t", "%42", "window-active-style", "bg=#fdf6e3") in style_calls


def test_reapply_agent_colors_fallback_styles_tracked_session_panes():
    """Theme refresh should style mapped panes even when active/sticky specs are empty."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    manager._sticky_specs = []
    manager._active_spec = None
    manager.state.session_to_pane = {"sid-1": "%77"}
    manager._session_catalog = {
        "sid-1": SimpleNamespace(session_id="sid-1", tmux_session_name="tc_sid-1", active_agent="claude")
    }

    with (
        patch.object(manager, "_get_pane_exists", return_value=True),
        patch.object(manager, "_set_tui_pane_background"),
        patch.object(manager, "_set_pane_background") as set_session_bg,
    ):
        manager.reapply_agent_colors()

    set_session_bg.assert_called_once_with("%77", "tc_sid-1", "claude", is_tree_selected=False)


def test_set_tui_pane_background_applies_haze_when_session_theming_on():
    """TUI pane gets haze when session theming is active (levels 1, 3, 4)."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    mock_run = Mock(return_value="")
    with (
        patch.object(manager, "_run_tmux", mock_run),
        patch.object(manager, "_get_pane_exists", return_value=True),
        patch.object(theme, "should_apply_session_theming", return_value=True),
        patch.object(theme, "get_tui_inactive_background", return_value="#e8e2d0"),
        patch.object(theme, "get_terminal_background", return_value="#fdf6e3"),
    ):
        manager._set_tui_pane_background()

    calls = [call.args for call in mock_run.call_args_list]
    assert ("set", "-p", "-t", "%1", "window-style", "bg=#e8e2d0") in calls
    assert ("set", "-p", "-t", "%1", "window-active-style", "bg=#fdf6e3") in calls
    assert ("set", "-w", "-t", "%1", "pane-border-style", "fg=#e8e2d0,bg=#e8e2d0") in calls
    assert ("set", "-w", "-t", "%1", "pane-active-border-style", "fg=#e8e2d0,bg=#e8e2d0") in calls


def test_set_tui_pane_background_native_when_session_theming_off():
    """TUI pane uses native defaults when session theming is off (levels 0, 2)."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    mock_run = Mock(return_value="")
    with (
        patch.object(manager, "_run_tmux", mock_run),
        patch.object(manager, "_get_pane_exists", return_value=True),
        patch.object(theme, "should_apply_session_theming", return_value=False),
    ):
        manager._set_tui_pane_background()

    calls = [call.args for call in mock_run.call_args_list]
    assert ("set", "-pu", "-t", "%1", "window-style") in calls
    assert ("set", "-pu", "-t", "%1", "window-active-style") in calls
    assert ("set", "-wu", "-t", "%1", "pane-border-style") in calls
    assert ("set", "-wu", "-t", "%1", "pane-active-border-style") in calls


def test_reconcile_prunes_dead_pane_ids():
    """_reconcile() removes session_to_pane entries whose pane no longer exists in tmux."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    manager.state.session_to_pane = {
        "sid-alive": "%10",
        "sid-dead": "%20",
        "sid-also-dead": "%30",
    }

    # list-panes returns only the TUI pane and one live session pane
    mock_run = Mock(return_value="%1\n%10\n")
    with patch.object(manager, "_run_tmux", mock_run):
        manager._reconcile()

    assert "sid-alive" in manager.state.session_to_pane
    assert "sid-dead" not in manager.state.session_to_pane
    assert "sid-also-dead" not in manager.state.session_to_pane


def test_reconcile_clears_active_session_id_when_active_pane_is_dead():
    """_reconcile() clears active_session_id when the active pane has died."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    manager.state.session_to_pane = {"sid-active": "%20"}
    manager.state.active_session_id = "sid-active"

    # list-panes returns only the TUI pane — session pane is dead
    mock_run = Mock(return_value="%1\n")
    with patch.object(manager, "_run_tmux", mock_run):
        manager._reconcile()

    assert manager.state.active_session_id is None
    assert "sid-active" not in manager.state.session_to_pane


def test_reconcile_preserves_active_when_pane_is_alive():
    """_reconcile() keeps active_session_id when its pane still exists."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    manager.state.session_to_pane = {"sid-active": "%10"}
    manager.state.active_session_id = "sid-active"

    mock_run = Mock(return_value="%1\n%10\n")
    with patch.object(manager, "_run_tmux", mock_run):
        manager._reconcile()

    assert manager.state.active_session_id == "sid-active"
    assert manager.state.session_to_pane["sid-active"] == "%10"


def test_cold_start_kills_orphaned_panes():
    """Cold-start init kills non-TUI panes left by a crashed process."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        # list-panes returns TUI pane + 2 orphans; _get_current_pane_id is called,
        # then _init_panes(is_reload=False) calls _kill_orphaned_panes.
        call_count = 0

        def side_effect(*args):
            nonlocal call_count
            if args[0] == "display-message":
                if "-t" in args and "#{session_name}" in args:
                    return "tc_tui"
                return "%1"
            if args[0] == "list-panes":
                return "%1\n%50\n%60\n"
            if args[0] == "kill-pane":
                call_count += 1
                return ""
            return ""

        with patch.object(TmuxPaneManager, "_run_tmux", side_effect=side_effect):
            manager = TmuxPaneManager(is_reload=False)

    # Two orphan panes (%50, %60) should have been killed
    assert call_count == 2


def test_reload_init_preserves_existing_panes():
    """Reload init discovers existing panes without killing them."""
    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        killed = []

        def side_effect(*args):
            if args[0] == "display-message":
                if "-t" in args and "#{session_name}" in args:
                    return "tc_tui"
                return "%1"
            if args[0] == "list-panes":
                return "%1\t\n%50\ttmux -u attach-session -t tc_sess1\n%60\ttmux -u attach-session -t tc_sess2\n"
            if args[0] == "kill-pane":
                killed.append(args)
                return ""
            return ""

        with patch.object(TmuxPaneManager, "_run_tmux", side_effect=side_effect):
            manager = TmuxPaneManager(is_reload=True)

    # No panes should be killed on reload
    assert killed == []
    # Discovered panes should be in the reload map
    assert manager._reload_session_panes == {"tc_sess1": "%50", "tc_sess2": "%60"}


def test_render_layout_split_windows_do_not_capture_focus_with_d_flag():
    """Pane splits used for layout updates should keep focus in the TUI pane."""

    with patch.dict(os.environ, {"TMUX": "1", "TMUX_PANE": "%1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    manager._session_catalog = {
        "sess-active": SimpleNamespace(
            session_id="sess-active", tmux_session_name="tc-active", active_agent="claude", computer="local"
        ),
        "sess-sticky": SimpleNamespace(
            session_id="sess-sticky", tmux_session_name="tc-sticky", active_agent="gpt-4", computer="local"
        ),
    }

    split_calls = 0

    def run_tmux_with_ids(*args):
        nonlocal split_calls
        if args and args[0] == "split-window":
            split_calls += 1
            return f"%{split_calls + 9}"
        return ""

    mock_run = Mock(side_effect=run_tmux_with_ids)
    with (
        patch.object(manager, "_run_tmux", mock_run),
        patch.object(manager, "_get_pane_exists", return_value=True),
        patch.object(theme, "get_agent_pane_inactive_background", return_value="#101010"),
        patch.object(theme, "get_agent_pane_active_background", return_value="#000000"),
        patch.object(theme, "get_agent_normal_color", return_value=15),
        patch.object(theme, "get_tui_inactive_background", return_value="#e8e2d0"),
        patch.object(theme, "get_terminal_background", return_value="#fbf8f1"),
    ):
        manager.apply_layout(
            active_session_id="sess-active",
            sticky_session_ids=["sess-sticky"],
            get_computer_info=lambda _computer: None,
            selected_session_id="sess-active",
            tree_node_has_focus=True,
        )

    split_windows = [call.args for call in mock_run.call_args_list if call.args and call.args[0] == "split-window"]
    assert split_windows, "expected layout to split at least one window"
    assert all("-d" in args for args in split_windows)
