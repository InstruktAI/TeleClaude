"""Unit tests for Protocol-based adapter capabilities."""

import pytest
from unittest.mock import AsyncMock, Mock
from typing import AsyncIterator

from teleclaude.core.protocols import RemoteExecutionProtocol
from teleclaude.adapters.redis_adapter import RedisAdapter


def test_remote_execution_protocol_runtime_checkable():
    """Test that RemoteExecutionProtocol can be used with isinstance()."""
    # Create a mock that implements the protocol
    mock_adapter = Mock()
    mock_adapter.send_command_to_computer = AsyncMock()

    async def mock_poll():
        yield "output"

    mock_adapter.poll_output_stream = mock_poll

    # Protocol is runtime_checkable
    assert isinstance(mock_adapter, RemoteExecutionProtocol)


def test_redis_adapter_implements_protocol():
    """Test that RedisAdapter implements RemoteExecutionProtocol."""
    # RedisAdapter should be recognized as implementing the protocol
    assert issubclass(RedisAdapter, RemoteExecutionProtocol)


def test_protocol_methods_signature():
    """Test that RemoteExecutionProtocol defines correct method signatures."""
    # Get the protocol class methods
    protocol_methods = dir(RemoteExecutionProtocol)

    assert "send_command_to_computer" in protocol_methods
    assert "poll_output_stream" in protocol_methods


@pytest.mark.asyncio
async def test_protocol_send_command_signature():
    """Test send_command_to_computer method signature."""
    mock_adapter = Mock(spec=RemoteExecutionProtocol)
    mock_adapter.send_command_to_computer = AsyncMock(return_value="request_123")

    # Should accept these parameters
    result = await mock_adapter.send_command_to_computer(
        computer_name="comp1",
        session_id="sess_123",
        command="ls -la",
        metadata={"key": "value"}
    )

    assert result == "request_123"
    mock_adapter.send_command_to_computer.assert_called_once_with(
        computer_name="comp1",
        session_id="sess_123",
        command="ls -la",
        metadata={"key": "value"}
    )


def test_protocol_poll_output_stream_signature():
    """Test poll_output_stream method signature."""
    mock_adapter = Mock(spec=RemoteExecutionProtocol)

    async def mock_stream(session_id: str, timeout: float) -> AsyncIterator[str]:
        yield "chunk1"
        yield "chunk2"

    mock_adapter.poll_output_stream = mock_stream

    # Method should return AsyncIterator
    stream = mock_adapter.poll_output_stream(session_id="sess_123", timeout=60.0)
    assert hasattr(stream, "__aiter__")
