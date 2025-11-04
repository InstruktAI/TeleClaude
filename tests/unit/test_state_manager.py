"""Unit tests for state_manager module."""

import pytest

from teleclaude.core import state_manager


@pytest.fixture(autouse=True)
def reset_state():
    """Reset module-level state before each test."""
    state_manager._active_polling_sessions.clear()
    state_manager._exit_markers.clear()
    state_manager._idle_notifications.clear()
    yield
    state_manager._active_polling_sessions.clear()
    state_manager._exit_markers.clear()
    state_manager._idle_notifications.clear()


class TestPollingState:
    """Test polling state management functions."""

    def test_is_polling_false_by_default(self):
        """Test session not polling by default."""
        assert state_manager.is_polling("test-session") is False

    def test_mark_polling(self):
        """Test marking session as polling."""
        state_manager.mark_polling("test-session")
        assert state_manager.is_polling("test-session") is True

    def test_unmark_polling(self):
        """Test unmarking session as polling."""
        state_manager.mark_polling("test-session")
        state_manager.unmark_polling("test-session")
        assert state_manager.is_polling("test-session") is False

    def test_unmark_polling_idempotent(self):
        """Test unmarking non-polling session is safe."""
        state_manager.unmark_polling("test-session")
        assert state_manager.is_polling("test-session") is False

    def test_multiple_sessions_independent(self):
        """Test multiple sessions tracked independently."""
        state_manager.mark_polling("session-1")
        state_manager.mark_polling("session-2")

        assert state_manager.is_polling("session-1") is True
        assert state_manager.is_polling("session-2") is True
        assert state_manager.is_polling("session-3") is False

        state_manager.unmark_polling("session-1")

        assert state_manager.is_polling("session-1") is False
        assert state_manager.is_polling("session-2") is True


class TestExitMarkerState:
    """Test exit marker state management functions."""

    def test_has_exit_marker_false_by_default(self):
        """Test session has no exit marker by default."""
        assert state_manager.has_exit_marker("test-session") is False

    def test_get_exit_marker_default_none(self):
        """Test getting exit marker returns default when not set."""
        result = state_manager.get_exit_marker("test-session")
        assert result is None

    def test_get_exit_marker_custom_default(self):
        """Test getting exit marker with custom default."""
        result = state_manager.get_exit_marker("test-session", default=False)
        assert result is False

    def test_set_exit_marker_true(self):
        """Test setting exit marker to True."""
        state_manager.set_exit_marker("test-session", True)
        assert state_manager.has_exit_marker("test-session") is True
        assert state_manager.get_exit_marker("test-session") is True

    def test_set_exit_marker_false(self):
        """Test setting exit marker to False."""
        state_manager.set_exit_marker("test-session", False)
        assert state_manager.has_exit_marker("test-session") is True
        assert state_manager.get_exit_marker("test-session") is False

    def test_remove_exit_marker(self):
        """Test removing exit marker."""
        state_manager.set_exit_marker("test-session", True)
        state_manager.remove_exit_marker("test-session")
        assert state_manager.has_exit_marker("test-session") is False
        assert state_manager.get_exit_marker("test-session") is None

    def test_remove_exit_marker_idempotent(self):
        """Test removing non-existent exit marker is safe."""
        state_manager.remove_exit_marker("test-session")
        assert state_manager.has_exit_marker("test-session") is False

    def test_exit_markers_independent(self):
        """Test exit markers for multiple sessions independent."""
        state_manager.set_exit_marker("session-1", True)
        state_manager.set_exit_marker("session-2", False)

        assert state_manager.get_exit_marker("session-1") is True
        assert state_manager.get_exit_marker("session-2") is False
        assert state_manager.get_exit_marker("session-3") is None


class TestIdleNotificationState:
    """Test idle notification state management functions."""

    def test_has_idle_notification_false_by_default(self):
        """Test session has no idle notification by default."""
        assert state_manager.has_idle_notification("test-session") is False

    def test_get_idle_notification_none_by_default(self):
        """Test getting idle notification returns None when not set."""
        result = state_manager.get_idle_notification("test-session")
        assert result is None

    def test_set_idle_notification(self):
        """Test setting idle notification message ID."""
        state_manager.set_idle_notification("test-session", "msg-123")
        assert state_manager.has_idle_notification("test-session") is True
        assert state_manager.get_idle_notification("test-session") == "msg-123"

    def test_remove_idle_notification_returns_value(self):
        """Test removing idle notification returns the message ID."""
        state_manager.set_idle_notification("test-session", "msg-456")
        result = state_manager.remove_idle_notification("test-session")
        assert result == "msg-456"
        assert state_manager.has_idle_notification("test-session") is False

    def test_remove_idle_notification_not_set(self):
        """Test removing non-existent idle notification returns None."""
        result = state_manager.remove_idle_notification("test-session")
        assert result is None

    def test_idle_notifications_independent(self):
        """Test idle notifications for multiple sessions independent."""
        state_manager.set_idle_notification("session-1", "msg-111")
        state_manager.set_idle_notification("session-2", "msg-222")

        assert state_manager.get_idle_notification("session-1") == "msg-111"
        assert state_manager.get_idle_notification("session-2") == "msg-222"
        assert state_manager.get_idle_notification("session-3") is None

        removed = state_manager.remove_idle_notification("session-1")
        assert removed == "msg-111"
        assert state_manager.get_idle_notification("session-1") is None
        assert state_manager.get_idle_notification("session-2") == "msg-222"

    def test_update_idle_notification(self):
        """Test updating idle notification (overwrite)."""
        state_manager.set_idle_notification("test-session", "msg-old")
        state_manager.set_idle_notification("test-session", "msg-new")
        assert state_manager.get_idle_notification("test-session") == "msg-new"
