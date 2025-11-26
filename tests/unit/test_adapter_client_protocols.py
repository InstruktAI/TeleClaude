"""Unit tests for AdapterClient's Protocol-based cross-computer orchestration."""

from typing import AsyncIterator
from unittest.mock import AsyncMock, Mock

import pytest

from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.protocols import RemoteExecutionProtocol


@pytest.fixture
def mock_transport_adapter():
    """Create mock adapter implementing RemoteExecutionProtocol."""
    adapter = Mock(spec=RemoteExecutionProtocol)
    adapter.send_request = AsyncMock(return_value="req_123")
    adapter.send_response = AsyncMock(return_value="resp_123")

    async def mock_stream(request_id: str, timeout: float = 300.0) -> AsyncIterator[str]:
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
async def test_send_request_success(adapter_client_with_transport, mock_transport_adapter):
    """Test sending request to remote computer via transport adapter."""
    # Execute
    stream_id = await adapter_client_with_transport.send_request(
        computer_name="comp1", request_id="req_123", command="ls -la", metadata={"key": "value"}
    )

    # Verify
    assert stream_id == "req_123"
    mock_transport_adapter.send_request.assert_called_once_with("comp1", "req_123", "ls -la", {"key": "value"})


@pytest.mark.asyncio
async def test_send_request_no_transport_fails(adapter_client_without_transport):
    """Test sending request fails when no transport adapter available."""
    with pytest.raises(RuntimeError, match="No transport adapter available"):
        await adapter_client_without_transport.send_request(
            computer_name="comp1", request_id="req_123", command="ls -la"
        )


@pytest.mark.asyncio
async def test_stream_session_output_success(adapter_client_with_transport):
    """Test streaming session output from remote request."""
    # Execute
    chunks = []
    async for chunk in adapter_client_with_transport.stream_session_output("req_123", timeout=60.0):
        chunks.append(chunk)

    # Verify
    assert chunks == ["chunk1", "chunk2"]


@pytest.mark.asyncio
async def test_stream_session_output_no_transport_fails(adapter_client_without_transport):
    """Test streaming session output fails when no transport adapter available."""
    with pytest.raises(RuntimeError, match="No transport adapter available"):
        stream = adapter_client_without_transport.stream_session_output("req_123")
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
    transport.send_request = AsyncMock(return_value="req_123")
    transport.send_response = AsyncMock(return_value="resp_123")

    client = AdapterClient()
    client.register_adapter("telegram", ui_adapter)
    client.register_adapter("redis", transport)

    # Execute cross-computer operation
    stream_id = await client.send_request("comp1", "req_123", "ls")

    # Verify - only transport adapter used
    assert stream_id == "req_123"
    transport.send_request.assert_called_once()
    assert not hasattr(ui_adapter, "send_request")  # UI adapter not called


@pytest.mark.asyncio
async def test_send_response_success(adapter_client_with_transport, mock_transport_adapter):
    """Test sending response for ephemeral request."""
    # Execute
    stream_id = await adapter_client_with_transport.send_response(request_id="req_123", data='{"status": "ok"}')

    # Verify
    assert stream_id == "resp_123"
    mock_transport_adapter.send_response.assert_called_once_with("req_123", '{"status": "ok"}')
