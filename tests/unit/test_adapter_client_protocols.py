"""Unit tests for AdapterClient's Protocol-based cross-computer orchestration."""

import pytest
from unittest.mock import AsyncMock, Mock
from typing import AsyncIterator

from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.protocols import RemoteExecutionProtocol


@pytest.fixture
def mock_transport_adapter():
    """Create mock adapter implementing RemoteExecutionProtocol."""
    adapter = Mock(spec=RemoteExecutionProtocol)
    adapter.send_command_to_computer = AsyncMock(return_value="req_123")

    async def mock_stream(session_id: str, timeout: float = 300.0) -> AsyncIterator[str]:
        yield "chunk1"
        yield "chunk2"

    adapter.poll_output_stream = mock_stream

    return adapter


@pytest.fixture
def mock_ui_adapter():
    """Create mock UI adapter (does NOT implement RemoteExecutionProtocol)."""
    # Create a real class that doesn't implement the protocol
    class UIAdapter:
        has_ui = True
        async def send_message(self, session_id, text, metadata=None):
            return "msg_123"

    return UIAdapter()


@pytest.fixture
def adapter_client_with_transport(mock_transport_adapter):
    """Create AdapterClient with transport adapter registered."""
    client = AdapterClient()
    client.register_adapter("redis", mock_transport_adapter)
    return client


@pytest.fixture
def adapter_client_without_transport(mock_ui_adapter):
    """Create AdapterClient with only UI adapter (no transport)."""
    client = AdapterClient()
    client.register_adapter("telegram", mock_ui_adapter)
    return client


@pytest.mark.asyncio
async def test_send_remote_command_success(adapter_client_with_transport, mock_transport_adapter):
    """Test sending command to remote computer via transport adapter."""
    # Execute
    request_id = await adapter_client_with_transport.send_remote_command(
        computer_name="comp1",
        session_id="sess_123",
        command="ls -la",
        metadata={"key": "value"}
    )

    # Verify
    assert request_id == "req_123"
    mock_transport_adapter.send_command_to_computer.assert_called_once_with(
        "comp1", "sess_123", "ls -la", {"key": "value"}
    )


@pytest.mark.asyncio
async def test_send_remote_command_no_transport_fails(adapter_client_without_transport):
    """Test sending command fails when no transport adapter available."""
    with pytest.raises(RuntimeError, match="No transport adapter available"):
        await adapter_client_without_transport.send_remote_command(
            computer_name="comp1",
            session_id="sess_123",
            command="ls -la"
        )


@pytest.mark.asyncio
async def test_poll_remote_output_success(adapter_client_with_transport):
    """Test streaming output from remote session."""
    # Execute
    chunks = []
    async for chunk in adapter_client_with_transport.poll_remote_output("sess_123", timeout=60.0):
        chunks.append(chunk)

    # Verify
    assert chunks == ["chunk1", "chunk2"]


@pytest.mark.asyncio
async def test_poll_remote_output_no_transport_fails(adapter_client_without_transport):
    """Test polling output fails when no transport adapter available."""
    with pytest.raises(RuntimeError, match="No transport adapter available"):
        stream = adapter_client_without_transport.poll_remote_output("sess_123")
        # Trigger the exception by starting iteration
        async for _ in stream:
            pass


def test_get_transport_adapter_returns_first_match(adapter_client_with_transport, mock_transport_adapter):
    """Test _get_transport_adapter returns first adapter implementing protocol."""
    # Execute
    transport = adapter_client_with_transport._get_transport_adapter()

    # Verify
    assert transport == mock_transport_adapter


def test_get_transport_adapter_fails_without_transport(adapter_client_without_transport):
    """Test _get_transport_adapter raises when no transport available."""
    with pytest.raises(RuntimeError, match="No transport adapter available"):
        adapter_client_without_transport._get_transport_adapter()


@pytest.mark.asyncio
async def test_mixed_adapters_only_transport_used_for_cross_computer():
    """Test AdapterClient with mixed adapters uses only transport for cross-computer ops."""
    # Create UI adapter (real class, not protocol)
    class UIAdapter:
        has_ui = True

    ui_adapter = UIAdapter()

    # Create transport adapter
    transport = Mock(spec=RemoteExecutionProtocol)
    transport.send_command_to_computer = AsyncMock(return_value="req_123")

    client = AdapterClient()
    client.register_adapter("telegram", ui_adapter)
    client.register_adapter("redis", transport)

    # Execute cross-computer operation
    request_id = await client.send_remote_command("comp1", "sess_123", "ls")

    # Verify - only transport adapter used
    assert request_id == "req_123"
    transport.send_command_to_computer.assert_called_once()
    assert not hasattr(ui_adapter, "send_command_to_computer")  # UI adapter not called
