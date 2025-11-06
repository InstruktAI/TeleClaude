"""Unit tests for base_adapter.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from teleclaude.adapters.base_adapter import BaseAdapter, AdapterError


class ConcreteAdapter(BaseAdapter):
    """Concrete implementation of BaseAdapter for testing."""

    async def start(self) -> None:
        """Start adapter."""
        pass

    async def stop(self) -> None:
        """Stop adapter."""
        pass

    async def send_message(self, session_id: str, message: str) -> str:
        """Send message."""
        return "msg-123"

    async def send_general_message(self, text: str, metadata=None) -> str:
        """Send general message."""
        return "msg-456"

    async def edit_message(self, session_id: str, message_id: str, text: str) -> bool:
        """Edit message."""
        return True

    async def delete_message(self, session_id: str, message_id: str) -> bool:
        """Delete message."""
        return True

    async def send_file(self, session_id: str, file_path: str, caption: str = "") -> bool:
        """Send file."""
        return True

    async def create_channel(self, session_id: str, title: str) -> str:
        """Create channel."""
        return "channel-123"

    async def update_channel_title(self, channel_id: str, title: str) -> bool:
        """Update channel title."""
        return True

    async def delete_channel(self, channel_id: str) -> bool:
        """Delete channel."""
        return True

    async def set_channel_status(self, channel_id: str, status: str) -> bool:
        """Set channel status."""
        return True

    async def discover_peers(self):
        """Discover peers."""
        return []


class TestBaseAdapter:
    """Tests for BaseAdapter class."""

    def test_adapter_creation(self):
        """Test creating adapter instance."""
        adapter = ConcreteAdapter()

        assert adapter._message_callbacks == []
        assert adapter._file_callbacks == []
        assert adapter._voice_callbacks == []
        assert adapter._command_callbacks == []
        assert adapter._topic_closed_callbacks == []

    def test_on_message_registration(self):
        """Test registering message callback."""
        adapter = ConcreteAdapter()
        callback = AsyncMock()

        adapter.on_message(callback)

        assert callback in adapter._message_callbacks

    def test_on_file_registration(self):
        """Test registering file callback."""
        adapter = ConcreteAdapter()
        callback = AsyncMock()

        adapter.on_file(callback)

        assert callback in adapter._file_callbacks

    def test_on_voice_registration(self):
        """Test registering voice callback."""
        adapter = ConcreteAdapter()
        callback = AsyncMock()

        adapter.on_voice(callback)

        assert callback in adapter._voice_callbacks

    def test_on_command_registration(self):
        """Test registering command callback."""
        adapter = ConcreteAdapter()
        callback = AsyncMock()

        adapter.on_command(callback)

        assert callback in adapter._command_callbacks

    def test_on_topic_closed_registration(self):
        """Test registering topic closed callback."""
        adapter = ConcreteAdapter()
        callback = AsyncMock()

        adapter.on_topic_closed(callback)

        assert callback in adapter._topic_closed_callbacks

    @pytest.mark.asyncio
    async def test_emit_message(self):
        """Test emitting message to callbacks."""
        adapter = ConcreteAdapter()
        callback1 = AsyncMock()
        callback2 = AsyncMock()

        adapter.on_message(callback1)
        adapter.on_message(callback2)

        await adapter._emit_message("session-123", "test message", {"user_id": 456})

        callback1.assert_called_once_with("session-123", "test message", {"user_id": 456})
        callback2.assert_called_once_with("session-123", "test message", {"user_id": 456})

    @pytest.mark.asyncio
    async def test_emit_file(self):
        """Test emitting file to callbacks."""
        adapter = ConcreteAdapter()
        callback = AsyncMock()

        adapter.on_file(callback)

        await adapter._emit_file("session-123", "/tmp/file.txt", {"user_id": 456})

        callback.assert_called_once_with("session-123", "/tmp/file.txt", {"user_id": 456})

    @pytest.mark.asyncio
    async def test_emit_voice(self):
        """Test emitting voice to callbacks."""
        adapter = ConcreteAdapter()
        callback = AsyncMock()

        adapter.on_voice(callback)

        await adapter._emit_voice("session-123", "/tmp/audio.ogg", {"duration": 5})

        callback.assert_called_once_with("session-123", "/tmp/audio.ogg", {"duration": 5})

    @pytest.mark.asyncio
    async def test_emit_command(self):
        """Test emitting command to callbacks."""
        adapter = ConcreteAdapter()
        callback = AsyncMock()

        adapter.on_command(callback)

        await adapter._emit_command("cancel", [], {"session_id": "test-123"})

        callback.assert_called_once_with("cancel", [], {"session_id": "test-123"})

    @pytest.mark.asyncio
    async def test_emit_topic_closed(self):
        """Test emitting topic closed to callbacks."""
        adapter = ConcreteAdapter()
        callback = AsyncMock()

        adapter.on_topic_closed(callback)

        await adapter._emit_topic_closed("session-123", {"user_id": 456})

        callback.assert_called_once_with("session-123", {"user_id": 456})

    @pytest.mark.asyncio
    async def test_emit_multiple_callbacks(self):
        """Test emitting to multiple callbacks."""
        adapter = ConcreteAdapter()
        callback1 = AsyncMock()
        callback2 = AsyncMock()
        callback3 = AsyncMock()

        adapter.on_command(callback1)
        adapter.on_command(callback2)
        adapter.on_command(callback3)

        await adapter._emit_command("exit", [], {"session_id": "test-123"})

        callback1.assert_called_once()
        callback2.assert_called_once()
        callback3.assert_called_once()


class TestAdapterError:
    """Tests for AdapterError exception."""

    def test_adapter_error_creation(self):
        """Test creating AdapterError."""
        error = AdapterError("Test error message")

        assert str(error) == "Test error message"
        assert isinstance(error, Exception)

    def test_adapter_error_raise(self):
        """Test raising AdapterError."""
        with pytest.raises(AdapterError, match="Test error"):
            raise AdapterError("Test error")
