"""Unit tests for teleclaude__handle_agent_event behavior."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.events import AgentHookEvents
from teleclaude.mcp_server import TeleClaudeMCPServer


@pytest.fixture
def mock_server():
    """Create MCP server with mocked dependencies."""
    mock_client = MagicMock()
    mock_terminal_bridge = MagicMock()

    with patch("teleclaude.mcp_server.config") as mock_config:
        mock_config.computer.name = "TestComputer"
        server = TeleClaudeMCPServer(adapter_client=mock_client, terminal_bridge=mock_terminal_bridge)

    return server, mock_client


@pytest.mark.asyncio
async def test_handle_agent_event_returns_before_dispatch(mock_server) -> None:
    server, mock_client = mock_server
    block = asyncio.Event()

    async def _blocked(*_args, **_kwargs):
        await block.wait()
        return {"status": "success"}

    mock_client.handle_event = AsyncMock(side_effect=_blocked)

    mock_session = MagicMock()
    mock_session.session_id = "test-session"

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)
        mock_db.update_ux_state = AsyncMock()

        result = await server.teleclaude__handle_agent_event(
            "test-session",
            AgentHookEvents.AGENT_STOP,
            {"transcript_path": "/tmp/test.jsonl"},
        )

        assert result == "OK"
        await asyncio.sleep(0)
        mock_client.handle_event.assert_called_once()

        block.set()
        await asyncio.sleep(0)
