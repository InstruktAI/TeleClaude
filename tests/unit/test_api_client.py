"""Unit tests for TelecAPIClient."""

# type: ignore - test uses mocked httpx

import itertools
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from teleclaude.cli.api_client import APIError, TelecAPIClient


@pytest.fixture
def api_client():
    """Create API client instance."""
    return TelecAPIClient()


@pytest.mark.asyncio
async def test_connect_creates_client():
    """Test connect() initializes httpx client."""
    client = TelecAPIClient()
    assert client.is_connected is False

    await client.connect()
    assert client.is_connected is True

    await client.close()


@pytest.mark.asyncio
async def test_close_idempotent():
    """Test close() can be called multiple times."""
    client = TelecAPIClient()
    await client.connect()

    await client.close()
    assert client.is_connected is False

    # Should not raise
    await client.close()
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_list_sessions_success():
    """Test list_sessions returns parsed response."""
    client = TelecAPIClient()
    await client.connect()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = json.dumps(
        [
            {
                "session_id": "sess-1",
                "last_input_origin": "telegram",
                "title": "Test",
                "project_path": "/tmp",
                "thinking_mode": "slow",
                "active_agent": "claude",
                "status": "active",
                "created_at": None,
                "last_activity": None,
                "last_input": None,
                "last_output_summary": None,
                "tmux_session_name": None,
                "initiator_session_id": None,
                "computer": "local",
            }
        ]
    )

    with patch.object(client, "_request", new=AsyncMock(return_value=mock_response)):
        result = await client.list_sessions()

        assert len(result) == 1
        assert result[0].session_id == "sess-1"

    await client.close()


@pytest.mark.asyncio
async def test_connect_error_debounced_logging():
    """Log connect errors at most once per debounce window."""
    client = TelecAPIClient()
    await client.connect()

    with patch.object(client._client, "get", side_effect=httpx.ConnectError("boom")):
        with patch("teleclaude.cli.api_client.API_CONNECT_RETRY_DELAYS_S", ()):
            with patch.object(client, "_now_monotonic", side_effect=itertools.count(start=0.0, step=5.0)):
                with patch.object(client, "_wait_for_socket", new=AsyncMock()):
                    with patch("teleclaude.cli.api_client.logger") as mock_logger:
                        with pytest.raises(APIError):
                            await client._request("GET", "/sessions")
                        with pytest.raises(APIError):
                            await client._request("GET", "/sessions")
                        with pytest.raises(APIError):
                            await client._request("GET", "/sessions")
                        assert len(mock_logger.debug.call_args_list) == 2

    await client.close()


@pytest.mark.asyncio
async def test_list_sessions_with_computer_filter():
    """Test list_sessions passes computer parameter."""
    client = TelecAPIClient()
    await client.connect()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "[]"

    with patch.object(client, "_request", new=AsyncMock(return_value=mock_response)):
        result = await client.list_sessions(computer="local")
        assert result == []

    await client.close()


@pytest.mark.asyncio
async def test_list_computers_success():
    """Test list_computers returns parsed response."""
    client = TelecAPIClient()
    await client.connect()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = json.dumps(
        [
            {
                "name": "local",
                "status": "online",
                "user": "me",
                "host": "localhost",
                "is_local": True,
                "tmux_binary": "tmux",
            }
        ]
    )

    with patch.object(client._client, "get", return_value=mock_response):
        result = await client.list_computers()

        assert len(result) == 1
        assert result[0].name == "local"

    await client.close()


@pytest.mark.asyncio
async def test_create_session_success():
    """Test create_session sends POST request."""
    client = TelecAPIClient()
    await client.connect()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = json.dumps({"status": "success", "session_id": "new-sess", "tmux_session_name": "tmux-1"})

    with patch.object(client, "_request", new=AsyncMock(return_value=mock_response)):
        result = await client.create_session(
            computer="local",
            project_path="/home/user/project",
            agent="claude",
            thinking_mode="slow",
        )

        assert result.session_id == "new-sess"

    await client.close()


@pytest.mark.asyncio
async def test_end_session_success():
    """Test end_session sends DELETE request."""
    client = TelecAPIClient()
    await client.connect()

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch.object(client, "_request", new=AsyncMock(return_value=mock_response)):
        result = await client.end_session(session_id="sess-1", computer="local")

        assert result is True

    await client.close()


@pytest.mark.asyncio
async def test_api_error_on_connect_error():
    """Test APIError raised on connection failure."""
    client = TelecAPIClient()
    await client.connect()

    with patch.object(client._client, "get", side_effect=httpx.ConnectError("Connection refused")):
        with patch("teleclaude.cli.api_client.API_CONNECT_RETRY_DELAYS_S", ()):
            with patch.object(client, "_wait_for_socket", new=AsyncMock()):
                with pytest.raises(APIError) as exc_info:
                    await client.list_sessions()

        assert "Cannot connect to API server" in str(exc_info.value)

    await client.close()


@pytest.mark.asyncio
async def test_api_error_on_timeout():
    """Test APIError raised on timeout."""
    client = TelecAPIClient()
    await client.connect()

    with patch.object(client._client, "get", side_effect=httpx.TimeoutException("Timeout")):
        with pytest.raises(APIError) as exc_info:
            await client.list_sessions()

    assert "request timed out" in str(exc_info.value).lower()

    await client.close()


@pytest.mark.asyncio
async def test_api_error_on_http_status_error():
    """Test APIError raised on HTTP error status."""
    client = TelecAPIClient()
    await client.connect()

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal server error"
    error = httpx.HTTPStatusError("Server error", request=MagicMock(), response=mock_response)

    with patch.object(client._client, "get", side_effect=error):
        with pytest.raises(APIError) as exc_info:
            await client.list_sessions()

        assert "500" in str(exc_info.value)

    await client.close()


@pytest.mark.asyncio
async def test_get_agent_availability():
    """Test get_agent_availability returns parsed response."""
    client = TelecAPIClient()
    await client.connect()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = json.dumps(
        {
            "claude": {
                "agent": "claude",
                "available": True,
                "unavailable_until": None,
                "reason": None,
                "error": None,
            }
        }
    )

    with patch.object(client._client, "get", return_value=mock_response):
        result = await client.get_agent_availability()

        assert "claude" in result
        assert result["claude"].available is True

    await client.close()
