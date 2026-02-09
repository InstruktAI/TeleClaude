"""Unit tests for TmuxPaneManager."""

import os
from unittest.mock import Mock, patch

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

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
