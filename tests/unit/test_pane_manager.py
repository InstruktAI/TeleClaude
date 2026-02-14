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


def test_show_session_tracks_parent_pane():
    """Test that show_session sets pane and session state when pane is created."""
    with patch.dict(os.environ, {"TMUX": "1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    mock_run = Mock(return_value="%5")
    with patch.object(manager, "_run_tmux", mock_run):
        manager.show_session(
            "parent-session",
            "claude",
            computer_info=ComputerInfo(name="local", is_local=True),
        )

    assert manager.state.parent_pane_id is not None
    assert manager.state.parent_session == "parent-session"
    # Verify at least one split-window command issued
    assert any(call.args[0] == "split-window" for call in mock_run.call_args_list)


def test_toggle_session_hides_when_already_showing():
    """Test that toggle_session hides panes when toggling the current session."""
    with patch.dict(os.environ, {"TMUX": "1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    manager.state.parent_session = "session-1"
    with patch.object(manager, "_render_layout", return_value=None):
        result = manager.toggle_session("session-1", "claude")

    assert result is False
    assert manager.active_session is None


def test_hide_sessions_kills_existing_panes_and_clears_state():
    """Test that hide_sessions cleans up panes and resets state."""
    with patch.dict(os.environ, {"TMUX": "1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    manager.state.parent_pane_id = "%10"
    manager.state.parent_session = "session-1"

    mock_run = Mock(return_value="")
    with patch.object(manager, "_run_tmux", mock_run), patch.object(manager, "_get_pane_exists", return_value=True):
        manager.hide_sessions()

    assert manager.state.parent_pane_id is None
    assert manager.state.parent_session is None
    # Verify kill-pane command issued for parent pane
    assert mock_run.call_args_list[0].args == ("kill-pane", "-t", "%10")


def test_set_pane_background_keeps_constant_fg_across_focus():
    """Session pane foreground should remain constant across active/inactive styles."""
    with patch.dict(os.environ, {"TMUX": "1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    mock_run = Mock(return_value="")
    with (
        patch.object(manager, "_run_tmux", mock_run),
        patch.object(theme, "get_agent_pane_inactive_background", return_value="#101010"),
        patch.object(theme, "get_agent_highlight_color", return_value=222),
        patch.object(theme, "get_current_mode", return_value=True),
        patch.object(theme, "get_terminal_background", return_value="#000000"),
    ):
        manager._set_pane_background("%9", "tc_test", "claude")

    style_calls = [call.args for call in mock_run.call_args_list if call.args[:4] == ("set", "-p", "-t", "%9")]
    assert ("set", "-p", "-t", "%9", "window-style", "fg=colour222,bg=#101010") in style_calls
    assert ("set", "-p", "-t", "%9", "window-active-style", "fg=colour222,bg=#000000") in style_calls


def test_doc_pane_background_is_applied_for_non_session_specs():
    """Doc/preview panes should get explicit neutral styles."""
    with patch.dict(os.environ, {"TMUX": "1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    mock_run = Mock(return_value="")
    with (
        patch.object(manager, "_run_tmux", mock_run),
        patch.object(theme, "get_tui_inactive_background", return_value="#e8e2d0"),
        patch.object(theme, "get_terminal_background", return_value="#fdf6e3"),
    ):
        manager._set_doc_pane_background("%42")

    style_calls = [call.args for call in mock_run.call_args_list if call.args[:4] == ("set", "-p", "-t", "%42")]
    assert ("set", "-p", "-t", "%42", "window-style", "fg=default,bg=#e8e2d0") in style_calls
    assert ("set", "-p", "-t", "%42", "window-active-style", "fg=default,bg=#fdf6e3") in style_calls


def test_reapply_agent_colors_fallback_styles_tracked_session_panes():
    """Theme refresh should style mapped panes even when active/sticky specs are empty."""
    with patch.dict(os.environ, {"TMUX": "1"}):
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

    set_session_bg.assert_called_once_with("%77", "tc_sid-1", "claude")


def test_set_tui_pane_background_sets_neutral_window_border_styles():
    """TUI layout should neutralize window border colors locally."""
    with patch.dict(os.environ, {"TMUX": "1"}):
        with patch.object(TmuxPaneManager, "_get_current_pane_id", return_value="%1"):
            manager = TmuxPaneManager()

    mock_run = Mock(return_value="")
    with (
        patch.object(manager, "_run_tmux", mock_run),
        patch.object(manager, "_get_pane_exists", return_value=True),
        patch.object(theme, "get_tui_inactive_background", return_value="#e8e2d0"),
        patch.object(theme, "get_terminal_background", return_value="#fdf6e3"),
    ):
        manager._set_tui_pane_background()

    calls = [call.args for call in mock_run.call_args_list]
    assert ("set", "-p", "-t", "%1", "window-active-style", "fg=default,bg=#fdf6e3") in calls
    assert ("set", "-w", "-t", "%1", "pane-border-style", "fg=#e8e2d0,bg=#e8e2d0") in calls
    assert ("set", "-w", "-t", "%1", "pane-active-border-style", "fg=#e8e2d0,bg=#e8e2d0") in calls
