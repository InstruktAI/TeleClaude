"""Unit tests for session lifecycle logger."""

import json
from unittest.mock import MagicMock, mock_open, patch


def test_log_lifecycle_event_writes_json_line():
    """Test that log_lifecycle_event writes JSON to file."""
    from teleclaude.core.session_lifecycle_logger import log_lifecycle_event

    m = mock_open()
    with patch("teleclaude.core.session_lifecycle_logger.LIFECYCLE_LOG_PATH") as mock_path:
        mock_file = MagicMock()
        mock_path.open.return_value.__enter__.return_value = mock_file

        log_lifecycle_event("test_event", "session-123-abc-def")

        # Verify file was opened for append
        mock_path.open.assert_called_once_with("a", encoding="utf-8")

        # Verify JSON was written
        assert mock_file.write.call_count == 1
        written_data = mock_file.write.call_args[0][0]
        assert written_data.endswith("\n")

        # Parse the JSON and verify fields
        event_data = json.loads(written_data.strip())
        assert "timestamp" in event_data
        assert event_data["event"] == "test_event"
        assert event_data["session_id"] == "session-"  # First 8 chars


def test_log_lifecycle_event_includes_optional_fields():
    """Test that log_lifecycle_event includes tmux and context when provided."""
    from teleclaude.core.session_lifecycle_logger import log_lifecycle_event

    with patch("teleclaude.core.session_lifecycle_logger.LIFECYCLE_LOG_PATH") as mock_path:
        mock_file = MagicMock()
        mock_path.open.return_value.__enter__.return_value = mock_file

        log_lifecycle_event(
            "test_event",
            "session-123-abc-def",
            tmux_session_name="tmux-session-123",
            context={"key": "value", "number": 42},
        )

        written_data = mock_file.write.call_args[0][0]
        event_data = json.loads(written_data.strip())

        # Verify optional fields included
        assert event_data["tmux"] == "tmux-session-123"
        assert event_data["context"]["key"] == "value"
        assert event_data["context"]["number"] == 42


def test_log_lifecycle_event_handles_write_failure():
    """Test that log_lifecycle_event handles file write errors."""
    from teleclaude.core.session_lifecycle_logger import log_lifecycle_event

    with patch("teleclaude.core.session_lifecycle_logger.LIFECYCLE_LOG_PATH") as mock_path:
        mock_path.open.side_effect = IOError("Permission denied")

        # Should not crash
        log_lifecycle_event("test_event", "session-123")

        # Verify open was attempted
        mock_path.open.assert_called_once()


def test_log_session_created_calls_log_lifecycle_event():
    """Test that log_session_created helper formats correctly."""
    from teleclaude.core.session_lifecycle_logger import log_session_created

    with patch("teleclaude.core.session_lifecycle_logger.log_lifecycle_event") as mock_log:
        log_session_created("session-123", "tmux-session-456", "My Session Title")

        mock_log.assert_called_once_with(
            "session_created",
            "session-123",
            "tmux-session-456",
            {"title": "My Session Title"},
        )


def test_log_polling_started_calls_log_lifecycle_event():
    """Test that log_polling_started helper formats correctly."""
    from teleclaude.core.session_lifecycle_logger import log_polling_started

    with patch("teleclaude.core.session_lifecycle_logger.log_lifecycle_event") as mock_log:
        log_polling_started("session-123", "tmux-session-456")

        mock_log.assert_called_once_with(
            "polling_started",
            "session-123",
            "tmux-session-456",
        )


def test_log_session_death_includes_metrics():
    """Test that log_session_death includes age and poll count."""
    from teleclaude.core.session_lifecycle_logger import log_session_death

    with patch("teleclaude.core.session_lifecycle_logger.log_lifecycle_event") as mock_log:
        log_session_death(
            "session-123",
            "tmux-session-456",
            age_seconds=123.456,
            poll_count=42,
            context={"extra": "data"},
        )

        mock_log.assert_called_once()
        call_args = mock_log.call_args

        # Verify event name and session info
        assert call_args[0][0] == "session_death_detected"
        assert call_args[0][1] == "session-123"
        assert call_args[0][2] == "tmux-session-456"

        # Verify context includes metrics
        context = call_args[0][3]
        assert context["age_seconds"] == 123.46  # Rounded to 2 decimals
        assert context["poll_count"] == 42
        assert context["extra"] == "data"
