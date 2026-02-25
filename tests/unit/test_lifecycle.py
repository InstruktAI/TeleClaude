"""Unit tests for daemon lifecycle helpers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.cache import DaemonCache
from teleclaude.core.lifecycle import DaemonLifecycle


@pytest.mark.asyncio
async def test_warm_local_sessions_cache_seeds_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Warm cache should seed local sessions from DB."""
    mock_config = MagicMock()
    mock_config.computer.name = "test-computer"
    monkeypatch.setattr("teleclaude.core.lifecycle.config", mock_config)

    lifecycle = DaemonLifecycle(
        client=MagicMock(),
        cache=DaemonCache(),
        shutdown_event=asyncio.Event(),
        task_registry=MagicMock(),
        log_background_task_exception=lambda _name: lambda _task: None,
        init_voice_handler=lambda: None,
        api_restart_max=1,
        api_restart_window_s=1.0,
        api_restart_backoff_s=0.1,
    )

    mock_session = MagicMock()
    mock_session.session_id = "sess-1"
    mock_session.last_input_origin = "telegram"
    mock_session.title = "Test Session"
    mock_session.project_path = "~"
    mock_session.thinking_mode = "slow"
    mock_session.active_agent = None
    mock_session.created_at = None
    mock_session.last_activity = None
    mock_session.last_message_sent = None
    mock_session.last_message_sent_at = None
    mock_session.last_output_raw = None
    mock_session.last_output_at = None
    mock_session.tmux_session_name = None
    mock_session.initiator_session_id = None

    lifecycle.cache.update_session = MagicMock()

    with patch(
        "teleclaude.core.lifecycle.db.list_sessions", new_callable=AsyncMock, return_value=[mock_session]
    ) as mock_list:
        await lifecycle._warm_local_sessions_cache()

    assert mock_list.call_args == ((), {"computer_name": "test-computer"})
    assert lifecycle.cache.update_session.call_args is not None
