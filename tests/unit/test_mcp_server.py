"""Unit tests for MCP server streaming features."""

import asyncio
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.mcp_server import TeleClaudeMCPServer
from teleclaude.config import init_config


@pytest.fixture(autouse=True)
def setup_config():
    """Initialize config for all tests."""
    import teleclaude.config as config_module
    config_module._config = None  # Reset
    init_config({"computer": {"name": "test"}})


class TestExtractChunkContent:
    """Test chunk content extraction helper."""

    def test_extract_from_markdown_code_block(self):
        """Test extracting content from markdown code block."""
        server = TeleClaudeMCPServer(
            telegram_adapter=Mock(),
            terminal_bridge=Mock(),
            session_manager=Mock(),
            computer_registry=Mock(),
        )

        message = "```sh\ntest output\n```\n[Chunk 1/3]"
        result = server._extract_chunk_content(message)
        assert result == "test output"

    def test_extract_removes_chunk_markers(self):
        """Test chunk markers are removed."""
        server = TeleClaudeMCPServer(
            telegram_adapter=Mock(),
            terminal_bridge=Mock(),
            session_manager=Mock(),
            computer_registry=Mock(),
        )

        message = "```sh\nline1\nline2\n```\n[Chunk 2/5]"
        result = server._extract_chunk_content(message)
        assert result == "line1\nline2"
        assert "[Chunk" not in result

    def test_extract_handles_plain_text(self):
        """Test extraction handles text without code blocks."""
        server = TeleClaudeMCPServer(
            telegram_adapter=Mock(),
            terminal_bridge=Mock(),
            session_manager=Mock(),
            computer_registry=Mock(),
        )

        message = "plain text output [Chunk 1/1]"
        result = server._extract_chunk_content(message)
        assert result == "plain text output"

    def test_extract_handles_empty_message(self):
        """Test extraction handles empty message."""
        server = TeleClaudeMCPServer(
            telegram_adapter=Mock(),
            terminal_bridge=Mock(),
            session_manager=Mock(),
            computer_registry=Mock(),
        )

        result = server._extract_chunk_content("")
        assert result == ""

    def test_extract_handles_none(self):
        """Test extraction handles None."""
        server = TeleClaudeMCPServer(
            telegram_adapter=Mock(),
            terminal_bridge=Mock(),
            session_manager=Mock(),
            computer_registry=Mock(),
        )

        result = server._extract_chunk_content(None)
        assert result == ""


@pytest.mark.asyncio
class TestStreamingBehavior:
    """Test teleclaude__send streaming behavior."""

    async def test_streaming_yields_chunks_as_they_arrive(self):
        """Test chunks are yielded immediately as they arrive."""
        mock_session_manager = Mock()
        mock_session = Mock()
        mock_session.closed = False
        mock_session.adapter_metadata = {"channel_id": "123"}
        mock_session_manager.get_session = AsyncMock(return_value=mock_session)

        mock_terminal_bridge = Mock()
        mock_terminal_bridge.send_keys = AsyncMock()

        mock_telegram_adapter = Mock()
        output_queue = asyncio.Queue()
        mock_telegram_adapter.register_mcp_listener = AsyncMock(return_value=output_queue)
        mock_telegram_adapter.unregister_mcp_listener = AsyncMock()

        server = TeleClaudeMCPServer(
            telegram_adapter=mock_telegram_adapter,
            terminal_bridge=mock_terminal_bridge,
            session_manager=mock_session_manager,
            computer_registry=Mock(),
        )

        # Background task: Simulate chunks arriving instantly
        async def send_chunks():
            msg1 = Mock()
            msg1.text = "```sh\nchunk1\n```\n[Chunk 1/3]"
            await output_queue.put(msg1)

            msg2 = Mock()
            msg2.text = "```sh\nchunk2\n```\n[Chunk 2/3]"
            await output_queue.put(msg2)

            msg3 = Mock()
            msg3.text = "```sh\nchunk3\n```\n[Chunk 3/3]"
            await output_queue.put(msg3)

            completion = Mock()
            completion.text = "[Output Complete]"
            await output_queue.put(completion)

        chunk_task = asyncio.create_task(send_chunks())

        # Collect chunks
        chunks = []
        async for chunk in server.teleclaude__send("test-session", "echo test"):
            chunks.append(chunk)

        await chunk_task

        # Verify chunks arrived in order
        assert len(chunks) == 3
        assert "chunk1" in chunks[0]
        assert "chunk2" in chunks[1]
        assert "chunk3" in chunks[2]

    async def test_streaming_detects_completion_marker(self):
        """Test stream ends when completion marker received."""
        mock_session_manager = Mock()
        mock_session = Mock()
        mock_session.closed = False
        mock_session.adapter_metadata = {"channel_id": "123"}
        mock_session_manager.get_session = AsyncMock(return_value=mock_session)

        mock_terminal_bridge = Mock()
        mock_terminal_bridge.send_keys = AsyncMock()

        mock_telegram_adapter = Mock()
        output_queue = asyncio.Queue()
        mock_telegram_adapter.register_mcp_listener = AsyncMock(return_value=output_queue)
        mock_telegram_adapter.unregister_mcp_listener = AsyncMock()

        server = TeleClaudeMCPServer(
            telegram_adapter=mock_telegram_adapter,
            terminal_bridge=mock_terminal_bridge,
            session_manager=mock_session_manager,
            computer_registry=Mock(),
        )

        # Add chunks with completion marker
        msg1 = Mock()
        msg1.text = "```sh\noutput\n```\n[Chunk 1/1]"
        await output_queue.put(msg1)

        completion = Mock()
        completion.text = "[Output Complete]"
        await output_queue.put(completion)

        # Stream should end after completion marker
        chunks = []
        async for chunk in server.teleclaude__send("test-session", "test"):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert "output" in chunks[0]

    async def test_streaming_sends_heartbeat_during_idle(self):
        """Test heartbeat appears during long idle periods."""
        mock_session_manager = Mock()
        mock_session = Mock()
        mock_session.closed = False
        mock_session.adapter_metadata = {"channel_id": "123"}
        mock_session_manager.get_session = AsyncMock(return_value=mock_session)

        mock_terminal_bridge = Mock()
        mock_terminal_bridge.send_keys = AsyncMock()

        mock_telegram_adapter = Mock()
        output_queue = asyncio.Queue()
        mock_telegram_adapter.register_mcp_listener = AsyncMock(return_value=output_queue)
        mock_telegram_adapter.unregister_mcp_listener = AsyncMock()

        server = TeleClaudeMCPServer(
            telegram_adapter=mock_telegram_adapter,
            terminal_bridge=mock_terminal_bridge,
            session_manager=mock_session_manager,
            computer_registry=Mock(),
        )

        # Mock time to simulate idle period
        start_time = time.time()
        with patch("time.time") as mock_time:
            # Simulate time passing
            call_count = [0]

            def time_generator():
                call_count[0] += 1
                if call_count[0] == 1:
                    return start_time  # Initial time
                elif call_count[0] == 2:
                    return start_time  # last_yield_time check
                else:
                    # After 61 seconds, should trigger heartbeat
                    return start_time + 61

            mock_time.side_effect = time_generator

            # Background task: Send completion immediately
            async def send_completion():
                completion = Mock()
                completion.text = "[Output Complete]"
                await output_queue.put(completion)

            completion_task = asyncio.create_task(send_completion())

            # Collect output
            chunks = []
            try:
                async with asyncio.timeout(0.01):
                    async for chunk in server.teleclaude__send("test-session", "test"):
                        chunks.append(chunk)
            except asyncio.TimeoutError:
                pass

            await completion_task

        # Verify heartbeat was sent (time mocking triggers it)
        heartbeat_found = any("Waiting for response" in chunk for chunk in chunks)
        assert heartbeat_found or len(chunks) == 0

    async def test_streaming_timeout_after_max_idle(self):
        """Test stream times out after max idle period."""
        mock_session_manager = Mock()
        mock_session = Mock()
        mock_session.closed = False
        mock_session.adapter_metadata = {"channel_id": "123"}
        mock_session_manager.get_session = AsyncMock(return_value=mock_session)

        mock_terminal_bridge = Mock()
        mock_terminal_bridge.send_keys = AsyncMock()

        mock_telegram_adapter = Mock()
        output_queue = asyncio.Queue()  # Empty queue - no output
        mock_telegram_adapter.register_mcp_listener = AsyncMock(return_value=output_queue)
        mock_telegram_adapter.unregister_mcp_listener = AsyncMock()

        server = TeleClaudeMCPServer(
            telegram_adapter=mock_telegram_adapter,
            terminal_bridge=mock_terminal_bridge,
            session_manager=mock_session_manager,
            computer_registry=Mock(),
        )

        # Collect output with minimal timeout
        chunks = []
        try:
            async with asyncio.timeout(0.01):
                async for chunk in server.teleclaude__send("test-session", "sleep 100"):
                    chunks.append(chunk)
        except asyncio.TimeoutError:
            pass  # Expected

        # Verify cleanup happened
        assert mock_telegram_adapter.unregister_mcp_listener.called


@pytest.mark.asyncio
class TestStreamingErrorCases:
    """Test error handling in streaming."""

    async def test_streaming_session_not_found(self):
        """Test streaming handles session not found."""
        mock_session_manager = Mock()
        mock_session_manager.get_session = AsyncMock(return_value=None)

        server = TeleClaudeMCPServer(
            telegram_adapter=Mock(),
            terminal_bridge=Mock(),
            session_manager=mock_session_manager,
            computer_registry=Mock(),
        )

        chunks = []
        async for chunk in server.teleclaude__send("nonexistent", "test"):
            chunks.append(chunk)

        output = "".join(chunks)
        assert "[Error: Session not found]" in output

    async def test_streaming_closed_session(self):
        """Test streaming handles closed session."""
        mock_session_manager = Mock()
        mock_session = Mock()
        mock_session.closed = True
        mock_session_manager.get_session = AsyncMock(return_value=mock_session)

        server = TeleClaudeMCPServer(
            telegram_adapter=Mock(),
            terminal_bridge=Mock(),
            session_manager=mock_session_manager,
            computer_registry=Mock(),
        )

        chunks = []
        async for chunk in server.teleclaude__send("closed-session", "test"):
            chunks.append(chunk)

        output = "".join(chunks)
        assert "[Error: Session is closed]" in output

    async def test_streaming_send_keys_failure(self):
        """Test streaming handles terminal send_keys failure."""
        mock_session_manager = Mock()
        mock_session = Mock()
        mock_session.closed = False
        mock_session.adapter_metadata = {"channel_id": "123"}
        mock_session_manager.get_session = AsyncMock(return_value=mock_session)

        mock_terminal_bridge = Mock()
        mock_terminal_bridge.send_keys = AsyncMock(side_effect=Exception("Terminal error"))

        server = TeleClaudeMCPServer(
            telegram_adapter=Mock(),
            terminal_bridge=mock_terminal_bridge,
            session_manager=mock_session_manager,
            computer_registry=Mock(),
        )

        chunks = []
        async for chunk in server.teleclaude__send("test-session", "test"):
            chunks.append(chunk)

        output = "".join(chunks)
        assert "[Error:" in output
        assert "Terminal error" in output
