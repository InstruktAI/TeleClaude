"""Unit tests for models.py."""

import json
from datetime import datetime

from teleclaude.core.models import Recording, Session


class TestSession:
    """Tests for Session model."""

    def test_session_creation_minimal(self):
        """Test creating session with minimal fields."""
        session = Session(
            session_id="test-123", computer_name="TestPC", tmux_session_name="test-tmux", origin_adapter="telegram", title="Test Session"
        )

        assert session.session_id == "test-123"
        assert session.computer_name == "TestPC"
        assert session.tmux_session_name == "test-tmux"
        assert session.origin_adapter== "telegram"
        assert session.closed is False

    def test_session_creation_with_all_fields(self):
        """Test creating session with all fields."""
        now = datetime.now()
        metadata = {"topic_id": 123}

        session = Session(
            session_id="test-456",
            computer_name="TestPC",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Test Session",
            adapter_metadata=metadata,
            closed=True,
            created_at=now,
            last_activity=now,
            terminal_size="120x40",
            working_directory="/tmp",
        )

        assert session.title == "Test Session"
        assert session.adapter_metadata == metadata
        assert session.closed is True
        assert session.created_at == now
        assert session.last_activity == now
        assert session.terminal_size == "120x40"
        assert session.working_directory == "/tmp"

    def test_session_to_dict(self):
        """Test converting session to dictionary."""
        now = datetime.now()
        metadata = {"topic_id": 123, "user_id": 456}

        session = Session(
            session_id="test-789",
            computer_name="TestPC",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
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
            origin_adapter="telegram",
            title="Test Session",
            created_at=None,
            last_activity=None,
        )

        data = session.to_dict()

        # None values should be preserved
        assert data["created_at"] is None
        assert data["last_activity"] is None

    def test_session_to_dict_with_none_metadata(self):
        """Test to_dict with None metadata."""
        session = Session(
            session_id="test-no-meta",
            computer_name="TestPC",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Test Session",
            adapter_metadata=None,
        )

        data = session.to_dict()

        # None metadata should be preserved
        assert data["adapter_metadata"] is None

    def test_session_from_dict(self):
        """Test creating session from dictionary."""
        now = datetime.now()
        metadata = {"topic_id": 123}

        data = {
            "session_id": "test-dict",
            "computer_name": "TestPC",
            "tmux_session_name": "test-tmux",
            "adapter_type": "telegram",
            "title": "Test",
            "adapter_metadata": json.dumps(metadata),
            "status": "active",
            "created_at": now.isoformat(),
            "last_activity": now.isoformat(),
            "terminal_size": "80x24",
            "working_directory": "~",
        }

        session = Session.from_dict(data)

        assert session.session_id == "test-dict"
        assert session.computer_name == "TestPC"
        assert isinstance(session.created_at, datetime)
        assert isinstance(session.last_activity, datetime)
        # Metadata should be deserialized from JSON
        assert session.adapter_metadata == metadata

    def test_session_from_dict_with_datetime_objects(self):
        """Test from_dict when datetimes are already datetime objects."""
        now = datetime.now()

        data = {
            "session_id": "test-dt",
            "computer_name": "TestPC",
            "tmux_session_name": "test-tmux",
            "adapter_type": "telegram",
            "title": "Test Session",
            "created_at": now,  # Already datetime, not string
            "last_activity": now,
        }

        session = Session.from_dict(data)

        # Should handle datetime objects gracefully
        assert session.created_at == now
        assert session.last_activity == now

    def test_session_from_dict_with_dict_metadata(self):
        """Test from_dict when metadata is already a dict."""
        metadata = {"topic_id": 999}

        data = {
            "session_id": "test-dict-meta",
            "computer_name": "TestPC",
            "tmux_session_name": "test-tmux",
            "adapter_type": "telegram",
            "title": "Test Session",
            "adapter_metadata": metadata,  # Already dict, not JSON string
        }

        session = Session.from_dict(data)

        # Should handle dict metadata gracefully
        assert session.adapter_metadata == metadata

    def test_session_roundtrip(self):
        """Test session to_dict -> from_dict roundtrip."""
        now = datetime.now()
        metadata = {"topic_id": 123, "user_id": 456}

        original = Session(
            session_id="test-roundtrip",
            computer_name="TestPC",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Roundtrip Test",
            adapter_metadata=metadata,
            closed=False,
            created_at=now,
            last_activity=now,
            terminal_size="100x30",
            working_directory="/home/user",
        )

        # Convert to dict and back
        data = original.to_dict()
        restored = Session.from_dict(data)

        # Should match original
        assert restored.session_id == original.session_id
        assert restored.computer_name == original.computer_name
        assert restored.tmux_session_name == original.tmux_session_name
        assert restored.origin_adapter == original.origin_adapter
        assert restored.title == original.title
        assert restored.closed == original.closed
        assert restored.terminal_size == original.terminal_size
        assert restored.working_directory == original.working_directory


class TestRecording:
    """Tests for Recording model."""

    def test_recording_creation(self):
        """Test creating recording."""
        recording = Recording(
            recording_id=1, session_id="session-123", file_path="/tmp/recording.txt", recording_type="text"
        )

        assert recording.recording_id == 1
        assert recording.session_id == "session-123"
        assert recording.file_path == "/tmp/recording.txt"
        assert recording.recording_type == "text"

    def test_recording_with_timestamp(self):
        """Test recording with timestamp."""
        now = datetime.now()

        recording = Recording(
            recording_id=2,
            session_id="session-456",
            file_path="/tmp/recording.mp4",
            recording_type="video",
            timestamp=now,
        )

        assert recording.timestamp == now

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

    def test_recording_from_dict(self):
        """Test creating recording from dictionary."""
        now = datetime.now()

        data = {
            "recording_id": 5,
            "session_id": "session-dict",
            "file_path": "/tmp/dict.txt",
            "recording_type": "text",
            "timestamp": now.isoformat(),
        }

        recording = Recording.from_dict(data)

        assert recording.recording_id == 5
        assert recording.session_id == "session-dict"
        assert isinstance(recording.timestamp, datetime)

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
        assert recording.timestamp == now

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
        assert restored.recording_type == original.recording_type
