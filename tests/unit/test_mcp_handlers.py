"""Unit tests for MCP handler helpers."""

from __future__ import annotations

import os

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.mcp.handlers import MCPHandlersMixin


class DummyHandlers(MCPHandlersMixin):
    """Minimal handler implementation for helper testing."""

    client = object()
    computer_name = "local"

    def _is_local_computer(self, computer: str) -> bool:
        return computer == "local"

    async def _send_remote_request(
        self, *args: object, **kwargs: object
    ) -> dict[str, object]:  # guard: loose-dict - test stub
        raise NotImplementedError

    async def _register_listener_if_present(self, target_session_id: str, caller_session_id: str | None = None) -> None:
        raise NotImplementedError

    def _track_background_task(self, task: object, label: str) -> None:
        raise NotImplementedError


def test_extract_tmux_session_name_returns_none_for_non_success():
    """Test that _extract_tmux_session_name returns None on non-success results."""
    handler = DummyHandlers()

    assert handler._extract_tmux_session_name({"status": "error"}) is None
    assert handler._extract_tmux_session_name("not-a-dict") is None


def test_extract_tmux_session_name_returns_value_when_present():
    """Test that _extract_tmux_session_name returns tmux_session_name from result data."""
    handler = DummyHandlers()

    result = {"status": "success", "data": {"tmux_session_name": "tmux-123"}}

    assert handler._extract_tmux_session_name(result) == "tmux-123"


def test_extract_tmux_session_name_handles_missing_data():
    """Test that _extract_tmux_session_name returns None when data is malformed."""
    handler = DummyHandlers()

    assert handler._extract_tmux_session_name({"status": "success", "data": "not-a-dict"}) is None
    assert handler._extract_tmux_session_name({"status": "success", "data": {}}) is None
