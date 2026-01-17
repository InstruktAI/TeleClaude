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
        patch("teleclaude.daemon.tmux_bridge.session_exists", new=AsyncMock(return_value=True)),
        patch("teleclaude.daemon.tmux_bridge.is_pane_dead", new=AsyncMock(return_value=False)),
        patch("teleclaude.daemon.tmux_bridge.is_process_running", new=AsyncMock(return_value=False)),
        patch("teleclaude.daemon.session_cleanup.terminate_session", new=AsyncMock()),
        patch("teleclaude.daemon.polling_coordinator.is_polling", new=AsyncMock(return_value=False)),
        patch("teleclaude.daemon.polling_coordinator.schedule_polling", new=AsyncMock()),
    ):
        await daemon._poller_watch_iteration()

    daemon.client.ensure_ui_channels.assert_called_once_with(session, session.title)


@pytest.mark.asyncio
async def test_poller_watch_recreates_missing_tmux_session():
    """Ensure poller watch recreates missing tmux session before polling."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = Mock()
    daemon.client.ensure_ui_channels = AsyncMock()
    daemon.output_poller = Mock()
    daemon._get_output_file_path = Mock()
    daemon._ensure_tmux_session = AsyncMock(return_value=True)

    session = Session(
        session_id="sess-456",
        computer_name="test",
        tmux_session_name="tc_sess_456",
        origin_adapter="rest",
        title="Test Session 2",
        adapter_metadata=SessionAdapterMetadata(),
    )

    with (
        patch("teleclaude.daemon.db.get_active_sessions", new=AsyncMock(return_value=[session])),
        patch("teleclaude.daemon.tmux_bridge.session_exists", new=AsyncMock(return_value=False)),
        patch("teleclaude.daemon.tmux_bridge.is_pane_dead", new=AsyncMock(return_value=False)),
        patch("teleclaude.daemon.session_cleanup.terminate_session", new=AsyncMock()),
        patch("teleclaude.daemon.polling_coordinator.is_polling", new=AsyncMock(return_value=False)),
        patch("teleclaude.daemon.polling_coordinator.schedule_polling", new=AsyncMock()),
    ):
        await daemon._poller_watch_iteration()

    daemon._ensure_tmux_session.assert_called_once_with(session)


@pytest.mark.asyncio
async def test_ensure_tmux_session_restores_agent_on_recreate():
    """Recreated tmux session should trigger agent restore when metadata available."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon._build_tmux_env_vars = AsyncMock(return_value={})

    session = Session(
        session_id="sess-789",
        computer_name="test",
        tmux_session_name="tc_sess_789",
        origin_adapter="rest",
        title="Restore Agent",
        adapter_metadata=SessionAdapterMetadata(),
        active_agent="gemini",
        native_session_id="native-123",
        thinking_mode="med",
    )

    with (
        patch("teleclaude.daemon.tmux_bridge.session_exists", new=AsyncMock(return_value=False)),
        patch("teleclaude.daemon.tmux_bridge.ensure_tmux_session", new=AsyncMock(return_value=True)),
        patch("teleclaude.daemon.tmux_bridge.send_keys", new=AsyncMock(return_value=True)) as send_keys,
        patch("teleclaude.daemon.resolve_working_dir", new=Mock(return_value="/tmp")),
        patch("teleclaude.daemon.get_agent_command", new=Mock(return_value="agent resume cmd")),
    ):
        created = await TeleClaudeDaemon._ensure_tmux_session(daemon, session)

    assert created is True
    send_keys.assert_called_once()
