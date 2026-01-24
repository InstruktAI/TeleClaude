"""Unit tests for MCP handler helpers."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.mcp.handlers import MCPHandlersMixin


class DummyHandlers(MCPHandlersMixin):
    """Minimal handler implementation for helper testing."""

    def __init__(self):
        self.client = AsyncMock()
        self.computer_name = "local"

    def _is_local_computer(self, computer: str) -> bool:
        return computer == "local"

    async def _get_caller_agent_info(self, caller_session_id: str | None) -> tuple[str | None, str | None]:
        return None, None

    async def _send_remote_request(
        self, *args: object, **kwargs: object
    ) -> dict[str, object]:  # guard: loose-dict - test stub
        raise NotImplementedError

    async def _register_listener_if_present(self, target_session_id: str, caller_session_id: str | None = None) -> None:
        pass

    def _track_background_task(self, task: object, label: str) -> None:
        pass


@pytest.mark.asyncio
async def test_start_session_extracts_tmux_name_from_event_result():
    """Test that teleclaude__start_session correctly extracts and returns tmux_session_name."""
    handler = DummyHandlers()
    mock_commands = MagicMock()
    mock_commands.create_session = AsyncMock()

    # Mock create_session to return a successful result with tmux name
    mock_commands.create_session.return_value = {
        "session_id": "sess-123",
        "tmux_session_name": "tmux-123",
    }

    with (
        patch("teleclaude.mcp.handlers.get_command_service", return_value=mock_commands),
        patch.object(handler, "_resolve_origin", new_callable=AsyncMock, return_value="telegram"),
    ):
        result = await handler.teleclaude__start_session(
            computer="local",
            project_path="/tmp",
            title="Test Session",
            message=None,  # skip agent start for simplicity
            caller_session_id="sess-parent",
        )

    assert result["status"] == "success"
    assert result["session_id"] == "sess-123"
    assert result["tmux_session_name"] == "tmux-123"


@pytest.mark.asyncio
async def test_start_session_handles_missing_tmux_name():
    """Test that teleclaude__start_session handles results where tmux_name is missing."""
    handler = DummyHandlers()
    mock_commands = MagicMock()
    mock_commands.create_session = AsyncMock()

    # Success but missing tmux name (or malformed data)
    mock_commands.create_session.return_value = {"session_id": "sess-123"}

    with (
        patch("teleclaude.mcp.handlers.get_command_service", return_value=mock_commands),
        patch.object(handler, "_resolve_origin", new_callable=AsyncMock, return_value="telegram"),
    ):
        result = await handler.teleclaude__start_session(
            computer="local",
            project_path="/tmp",
            title="Test Session",
            message=None,
            caller_session_id="sess-parent",
        )

    assert result["status"] == "success"
    assert result.get("tmux_session_name") is None
