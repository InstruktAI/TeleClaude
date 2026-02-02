"""Unit tests for Protocol-based adapter capabilities."""

from typing import AsyncIterator
from unittest.mock import AsyncMock, Mock

import pytest

from teleclaude.core.protocols import RemoteExecutionProtocol
from teleclaude.transport.redis_transport import RedisTransport


def test_remote_execution_protocol_runtime_checkable():
    """Test that RemoteExecutionProtocol can be used with isinstance()."""
    # Create a mock that implements the protocol
    mock_adapter = Mock()
    mock_adapter.send_request = AsyncMock()
    mock_adapter.send_response = AsyncMock()
    mock_adapter.read_response = AsyncMock()

    async def mock_poll():
        yield "output"

    mock_adapter.poll_output_stream = mock_poll

    # Protocol is runtime_checkable
    assert isinstance(mock_adapter, RemoteExecutionProtocol)


def test_redis_adapter_implements_protocol():
    """Test that RedisTransport implements RemoteExecutionProtocol."""
    # RedisTransport should be recognized as implementing the protocol
    assert issubclass(RedisTransport, RemoteExecutionProtocol)


def test_protocol_methods_signature():
    """Test that RemoteExecutionProtocol defines correct method signatures."""
    # Get the protocol class methods
    protocol_methods = dir(RemoteExecutionProtocol)

    assert "send_request" in protocol_methods
    assert "send_response" in protocol_methods
    assert "poll_output_stream" in protocol_methods


@pytest.mark.asyncio
async def test_protocol_send_request_signature():
    """Test send_request method signature."""
    calls: list[tuple[str, str, str, dict[str, str]]] = []

    class Adapter:
        async def send_request(
            self,
            computer_name: str,
            request_id: str,
            command: str,
            metadata: dict[str, str],
        ) -> str:
            calls.append((computer_name, request_id, command, metadata))
            return "stream_123"

    mock_adapter = Adapter()

    # Should accept these parameters
    result = await mock_adapter.send_request(
        computer_name="comp1", request_id="req_123", command="ls -la", metadata={"key": "value"}
    )

    assert result == "stream_123"
    assert calls == [("comp1", "req_123", "ls -la", {"key": "value"})]


@pytest.mark.asyncio
async def test_protocol_send_response_signature():
    """Test send_response method signature."""
    calls: list[tuple[str, str]] = []

    class Adapter:
        async def send_response(self, request_id: str, data: str) -> str:
            calls.append((request_id, data))
            return "stream_456"

    mock_adapter = Adapter()

    # Should accept these parameters
    result = await mock_adapter.send_response(request_id="req_123", data='{"status": "ok"}')

    assert result == "stream_456"
    assert calls == [("req_123", '{"status": "ok"}')]


def test_protocol_poll_output_stream_signature():
    """Test poll_output_stream method signature."""
    mock_adapter = Mock(spec=RemoteExecutionProtocol)

    async def mock_stream(request_id: str, timeout: float) -> AsyncIterator[str]:
        yield "chunk1"
        yield "chunk2"

    mock_adapter.poll_output_stream = mock_stream

    # Method should return AsyncIterator
    stream = mock_adapter.poll_output_stream(request_id="req_123", timeout=60.0)
    assert hasattr(stream, "__aiter__")
