"""Unit tests for TeleClaudeDaemon poller watch loop."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, Mock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core.models import Session, SessionAdapterMetadata
from teleclaude.daemon import TeleClaudeDaemon


@pytest.mark.asyncio
async def test_poller_watch_creates_ui_channel_when_missing_topic():
    """Test that poller watch ensures UI channels when topic metadata missing."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = Mock()
    daemon.client.ensure_ui_channels = AsyncMock()
    daemon.output_poller = Mock()
    daemon._get_output_file_path = Mock()

    session = Session(
        session_id="sess-123",
        computer_name="test",
        tmux_session_name="tc_sess",
        origin_adapter="rest",
        title="Test Session",
        adapter_metadata=SessionAdapterMetadata(),
    )

    with (
        patch("teleclaude.daemon.db.get_active_sessions", new=AsyncMock(return_value=[session])),
        patch("teleclaude.daemon.terminal_bridge.session_exists", new=AsyncMock(return_value=True)),
        patch("teleclaude.daemon.terminal_bridge.is_pane_dead", new=AsyncMock(return_value=False)),
        patch("teleclaude.daemon.terminal_bridge.is_process_running", new=AsyncMock(return_value=False)),
        patch("teleclaude.daemon.session_cleanup.cleanup_stale_session", new=AsyncMock()),
        patch("teleclaude.daemon.session_cleanup.terminate_session", new=AsyncMock()),
        patch("teleclaude.daemon.polling_coordinator.is_polling", new=AsyncMock(return_value=False)),
        patch("teleclaude.daemon.polling_coordinator.schedule_polling", new=AsyncMock()),
    ):
        await daemon._poller_watch_iteration()

    daemon.client.ensure_ui_channels.assert_called_once_with(session, session.title)
