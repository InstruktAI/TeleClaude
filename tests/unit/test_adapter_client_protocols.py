"""Unit tests for AdapterClient's Protocol-based cross-computer orchestration."""

from typing import AsyncIterator
from unittest.mock import AsyncMock, Mock

import pytest

from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.models import MessageMetadata
from teleclaude.core.origins import InputOrigin
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
    calls: list[tuple[str, str, MessageMetadata, None]] = []

    async def record_send_request(
        computer_name: str, command: str, metadata: MessageMetadata, request_id: str | None
    ) -> str:
        calls.append((computer_name, command, metadata, request_id))
        return "req_123"

    mock_transport_adapter.send_request = record_send_request

    # Execute
    metadata = MessageMetadata(origin=InputOrigin.API.value)
    stream_id = await adapter_client_with_transport.send_request(
        computer_name="comp1", command="ls -la", metadata=metadata
    )

    # Verify
    assert stream_id == "req_123"
    assert calls == [("comp1", "ls -la", metadata, None)]


@pytest.mark.asyncio
async def test_send_request_no_transport_fails(adapter_client_without_transport):
    """Test sending request fails when no transport adapter available."""
    with pytest.raises(RuntimeError, match="No transport adapter available"):
        metadata = MessageMetadata(origin=InputOrigin.API.value)
        await adapter_client_without_transport.send_request(computer_name="comp1", command="ls -la", metadata=metadata)


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
    calls: list[tuple[str, str, MessageMetadata, None]] = []

    async def record_send_request(
        computer_name: str, command: str, metadata: MessageMetadata, request_id: str | None
    ) -> str:
        calls.append((computer_name, command, metadata, request_id))
        return "req_123"

    transport.send_request = record_send_request
    transport.send_response = AsyncMock(return_value="resp_123")

    client = AdapterClient()
    client.register_adapter("telegram", ui_adapter)
    client.register_adapter("redis", transport)

    # Execute cross-computer operation
    metadata = MessageMetadata(origin=InputOrigin.API.value)
    stream_id = await client.send_request("comp1", "ls", metadata)

    # Verify - only transport adapter used
    assert stream_id == "req_123"
    assert calls == [("comp1", "ls", metadata, None)]
    assert not hasattr(ui_adapter, "send_request")  # UI adapter not called


@pytest.mark.asyncio
async def test_send_response_success(adapter_client_with_transport, mock_transport_adapter):
    """Test sending response for ephemeral request."""
    calls: list[tuple[str, str]] = []

    async def record_send_response(message_id: str, data: str) -> str:
        calls.append((message_id, data))
        return "resp_123"

    mock_transport_adapter.send_response = record_send_response

    # Execute
    stream_id = await adapter_client_with_transport.send_response(message_id="msg_123", data='{"status": "ok"}')

    # Verify
    assert stream_id == "resp_123"
    assert calls == [("msg_123", '{"status": "ok"}')]
