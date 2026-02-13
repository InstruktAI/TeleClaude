"""Unit tests for models.py."""

import json
from datetime import datetime

import pytest

from teleclaude.core.dates import ensure_utc
from teleclaude.core.models import Recording, RunAgentCommandArgs, Session, StartSessionArgs, ThinkingMode
from teleclaude.core.origins import InputOrigin


class TestSession:
    """Tests for Session model."""

    def test_session_to_dict(self):
        """Test converting session to dictionary."""
        now = datetime.now()
        metadata = {"topic_id": 123, "user_id": 456}

        session = Session(
            session_id="test-789",
            computer_name="TestPC",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata=metadata,
            created_at=now,
            last_activity=now,
        )

        data = session.to_dict()

        assert data["session_id"] == "test-789"
        assert data["computer_name"] == "TestPC"
        assert data["created_at"] == now.isoformat()
        assert data["last_activity"] == now.isoformat()
        # adapter_metadata should be JSON string
        assert isinstance(data["adapter_metadata"], str)
        assert json.loads(data["adapter_metadata"]) == metadata

    def test_session_to_dict_with_none_dates(self):
        """Test to_dict with None datetime fields."""
        session = Session(
            session_id="test-none",
            computer_name="TestPC",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            created_at=None,
            last_activity=None,
        )

        data = session.to_dict()

        # None values should be preserved
        assert data["created_at"] is None
        assert data["last_activity"] is None

    def test_session_from_dict_with_datetime_objects(self):
        """Test from_dict when datetimes are already datetime objects."""
        now = datetime.now()

        data = {
            "session_id": "test-dt",
            "computer_name": "TestPC",
            "tmux_session_name": "test-tmux",
            "last_input_origin": "telegram",
            "title": "Test Session",
            "created_at": now,  # Already datetime, not string
            "last_activity": now,
        }

        session = Session.from_dict(data)

        # Should handle datetime objects gracefully
        assert session.created_at == ensure_utc(now)
        assert session.last_activity == ensure_utc(now)

    def test_session_roundtrip(self):
        """Test session to_dict -> from_dict roundtrip."""
        now = datetime.now()
        metadata = {"topic_id": 123, "user_id": 456}

        original = Session(
            session_id="test-roundtrip",
            computer_name="TestPC",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Roundtrip Test",
            adapter_metadata=metadata,
            created_at=now,
            last_activity=now,
            project_path="/home/user",
        )

        # Convert to dict and back
        data = original.to_dict()
        restored = Session.from_dict(data)

        # Should match original
        assert restored.session_id == original.session_id
        assert restored.computer_name == original.computer_name
        assert restored.tmux_session_name == original.tmux_session_name
        assert restored.last_input_origin == original.last_input_origin
        assert restored.title == original.title
        assert restored.project_path == original.project_path

    def test_session_from_dict_parses_string_topic_id(self):
        """Test adapter_metadata topic_id stored as string is parsed to int."""
        now = datetime.now()
        data = {
            "session_id": "test-topic-id",
            "computer_name": "TestPC",
            "tmux_session_name": "test-tmux",
            "last_input_origin": "telegram",
            "title": "Test Session",
            "created_at": now,
            "last_activity": now,
            "adapter_metadata": json.dumps({"telegram": {"topic_id": "123", "output_message_id": "42"}}),
        }

        session = Session.from_dict(data)

        assert session.get_metadata().get_ui().get_telegram() is not None
        assert session.get_metadata().get_ui().get_telegram().topic_id == 123

    def test_session_from_dict_parses_footer_message_id(self):
        """Footer message id should hydrate from adapter metadata."""
        data = {
            "session_id": "test-footer",
            "computer_name": "TestPC",
            "tmux_session_name": "test-tmux",
            "last_input_origin": "telegram",
            "title": "Test Session",
            "adapter_metadata": json.dumps(
                {"telegram": {"topic_id": 123, "output_message_id": "42", "footer_message_id": "84"}}
            ),
        }

        session = Session.from_dict(data)
        assert session.get_metadata().get_ui().get_telegram() is not None
        assert session.get_metadata().get_ui().get_telegram().footer_message_id == "84"

    def test_session_from_dict_parses_legacy_threaded_footer_message_id(self):
        """Legacy threaded_footer_message_id should map to footer_message_id."""
        data = {
            "session_id": "test-legacy-footer",
            "computer_name": "TestPC",
            "tmux_session_name": "test-tmux",
            "last_input_origin": "telegram",
            "title": "Test Session",
            "adapter_metadata": json.dumps({"telegram": {"topic_id": 123, "threaded_footer_message_id": "99"}}),
        }

        session = Session.from_dict(data)
        assert session.get_metadata().get_ui().get_telegram() is not None
        assert session.get_metadata().get_ui().get_telegram().footer_message_id == "99"


class TestRecording:
    """Tests for Recording model."""

    def test_recording_to_dict(self):
        """Test converting recording to dictionary."""
        now = datetime.now()

        recording = Recording(
            recording_id=3, session_id="session-789", file_path="/tmp/test.txt", recording_type="text", timestamp=now
        )

        data = recording.to_dict()

        assert data["recording_id"] == 3
        assert data["session_id"] == "session-789"
        assert data["file_path"] == "/tmp/test.txt"
        assert data["recording_type"] == "text"
        assert data["timestamp"] == now.isoformat()

    def test_recording_to_dict_without_timestamp(self):
        """Test to_dict with None timestamp."""
        recording = Recording(
            recording_id=4, session_id="session-none", file_path="/tmp/none.txt", recording_type="text", timestamp=None
        )

        data = recording.to_dict()

        # None timestamp should be preserved
        assert data["timestamp"] is None

    def test_recording_from_dict_with_datetime_object(self):
        """Test from_dict when timestamp is already datetime object."""
        now = datetime.now()

        data = {
            "recording_id": 6,
            "session_id": "session-dt",
            "file_path": "/tmp/dt.txt",
            "recording_type": "text",
            "timestamp": now,  # Already datetime, not string
        }

        recording = Recording.from_dict(data)

        # Should handle datetime object gracefully
        assert recording.timestamp == ensure_utc(now)

    def test_recording_roundtrip(self):
        """Test recording to_dict -> from_dict roundtrip."""
        now = datetime.now()

        original = Recording(
            recording_id=7,
            session_id="session-roundtrip",
            file_path="/tmp/roundtrip.mp4",
            recording_type="video",
            timestamp=now,
        )

        # Convert to dict and back
        data = original.to_dict()
        restored = Recording.from_dict(data)

        # Should match original
        assert restored.recording_id == original.recording_id
        assert restored.session_id == original.session_id
        assert restored.file_path == original.file_path
        assert restored.recording_type == original.recording_type


class TestMcpArgs:
    """Tests for MCP argument parsing."""

    def test_start_session_args_accepts_deep(self):
        """Deep is now allowed in MCP args."""
        from teleclaude.core.models import ThinkingMode

        args = {
            "computer": "local",
            "project_path": "/tmp/project",
            "title": "Test",
            "message": "Hello",
            "thinking_mode": "deep",
        }
        parsed = StartSessionArgs.from_mcp(args, None)
        assert parsed.thinking_mode == ThinkingMode.DEEP

    def test_start_session_args_rejects_invalid_mode(self):
        """Invalid mode is rejected in MCP args."""
        args = {
            "computer": "local",
            "project_path": "/tmp/project",
            "title": "Test",
            "message": "Hello",
            "thinking_mode": "invalid",
        }
        with pytest.raises(ValueError, match="thinking_mode must be one of"):
            StartSessionArgs.from_mcp(args, None)

    def test_run_agent_command_args_accepts_deep(self):
        """Deep is now allowed in MCP args."""
        args = {
            "computer": "local",
            "command": "help",
            "thinking_mode": "deep",
        }
        parsed = RunAgentCommandArgs.from_mcp(args, None)
        assert parsed.thinking_mode == ThinkingMode.DEEP

    def test_run_agent_command_args_rejects_invalid_mode(self):
        """Invalid mode is rejected in MCP args."""
        args = {
            "computer": "local",
            "command": "help",
            "thinking_mode": "invalid",
        }
        with pytest.raises(ValueError, match="thinking_mode must be one of"):
            RunAgentCommandArgs.from_mcp(args, None)
