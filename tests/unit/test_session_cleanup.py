"""Unit tests for session cleanup utilities."""

from __future__ import annotations

import os
import shutil
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core import session_cleanup
from teleclaude.core.events import TeleClaudeEvents
from teleclaude.core.session_cleanup import (
    cleanup_all_stale_sessions,
    cleanup_orphan_mcp_wrappers,
    cleanup_orphan_workspaces,
    cleanup_stale_session,
    emit_recently_closed_session_events,
)


@pytest.mark.asyncio
async def test_cleanup_stale_session_detects_missing_tmux():
    """Paranoid test that cleanup_stale_session detects missing tmux and cleans up."""
    mock_session = MagicMock()
    mock_session.session_id = "stale-session-123"
    mock_session.tmux_session_name = "tc_stale"
    mock_session.last_input_origin = "telegram"
    mock_session.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)

    mock_adapter_client = MagicMock()

    terminate_calls = []

    async def record_terminate(*args, **kwargs):
        terminate_calls.append((args, kwargs))
        return True

    with (
        patch("teleclaude.core.session_cleanup.db.get_session", new_callable=AsyncMock) as mock_get,
        patch("teleclaude.core.session_cleanup.tmux_bridge.session_exists", new_callable=AsyncMock) as mock_exists,
        patch("teleclaude.core.session_cleanup.terminate_session", new=record_terminate),
    ):
        mock_get.return_value = mock_session
        mock_exists.return_value = False

        result = await cleanup_stale_session("stale-session-123", mock_adapter_client)

    assert result is True
    assert terminate_calls == [
        (
            ("stale-session-123", mock_adapter_client),
            {
                "reason": "stale",
                "session": mock_session,
                "kill_tmux": False,
                "delete_db": True,
            },
        )
    ]


@pytest.mark.asyncio
async def test_cleanup_session_resources_closes_conversation_links(tmp_path: Path):
    """Session cleanup should sever links for ended sessions."""
    mock_session = MagicMock()
    mock_session.session_id = "session-123"
    mock_session.project_path = None

    mock_adapter_client = MagicMock()
    mock_adapter_client.delete_channel = AsyncMock()

    with (
        patch("teleclaude.core.session_cleanup.cleanup_session_links", new_callable=AsyncMock) as mock_cleanup_links,
        patch("teleclaude.core.session_cleanup.pop_listeners", new_callable=AsyncMock) as mock_pop,
        patch(
            "teleclaude.core.session_cleanup.cleanup_caller_listeners", new_callable=AsyncMock
        ) as mock_cleanup_caller,
        patch("teleclaude.core.session_cleanup.get_session_output_dir", return_value=tmp_path / "missing"),
    ):
        mock_cleanup_links.return_value = 1
        mock_pop.return_value = []
        mock_cleanup_caller.return_value = 0

        await session_cleanup.cleanup_session_resources(mock_session, mock_adapter_client, delete_channel=False)

    mock_cleanup_links.assert_called_once_with("session-123")


@pytest.mark.asyncio
async def test_cleanup_stale_session_skips_healthy_session():
    """Paranoid test that cleanup_stale_session skips healthy sessions."""
    mock_session = MagicMock()
    mock_session.session_id = "healthy-session-123"
    mock_session.tmux_session_name = "tc_healthy"
    mock_session.last_input_origin = "telegram"
    mock_session.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)

    mock_adapter_client = MagicMock()

    with (
        patch("teleclaude.core.session_cleanup.db.get_session", new_callable=AsyncMock) as mock_get,
        patch("teleclaude.core.session_cleanup.tmux_bridge.session_exists", new_callable=AsyncMock) as mock_exists,
    ):
        mock_get.return_value = mock_session
        mock_exists.return_value = True

        result = await cleanup_stale_session("healthy-session-123", mock_adapter_client)

    assert result is False


@pytest.mark.asyncio
async def test_cleanup_all_stale_sessions_processes_all():
    """Paranoid test that cleanup_all_stale_sessions processes all active sessions."""
    mock_sessions = []
    for i in range(3):
        s = MagicMock()
        s.session_id = f"session-{i}"
        s.tmux_session_name = f"tc_session_{i}"
        s.last_input_origin = "telegram"
        s.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        mock_sessions.append(s)

    mock_adapter_client = MagicMock()

    stale_sessions = {"tc_session_0", "tc_session_2"}

    async def mock_session_exists(name):
        return name not in stale_sessions

    terminate_calls = []

    async def record_terminate(*args, **kwargs):
        terminate_calls.append((args, kwargs))
        return True

    with (
        patch("teleclaude.core.session_cleanup.db.get_active_sessions", new_callable=AsyncMock) as mock_get_active,
        patch("teleclaude.core.session_cleanup.db.get_session", new_callable=AsyncMock) as mock_get,
        patch("teleclaude.core.session_cleanup.tmux_bridge.session_exists", side_effect=mock_session_exists),
        patch("teleclaude.core.session_cleanup.terminate_session", new=record_terminate),
    ):
        mock_get_active.return_value = mock_sessions
        mock_get.side_effect = lambda sid: next((s for s in mock_sessions if s.session_id == sid), None)

        count = await cleanup_all_stale_sessions(mock_adapter_client)

    assert count == 2
    assert len(terminate_calls) == 2


@pytest.mark.asyncio
async def test_cleanup_all_stale_sessions_handles_empty_list():
    """Paranoid test that cleanup_all_stale_sessions handles no active sessions."""
    mock_adapter_client = MagicMock()

    with patch("teleclaude.core.session_cleanup.db.get_active_sessions", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = []

        count = await cleanup_all_stale_sessions(mock_adapter_client)

    assert count == 0


@pytest.mark.asyncio
async def test_cleanup_orphan_workspaces_removes_orphans(tmp_path: Path):
    """Paranoid test that cleanup_orphan_workspaces removes directories not in DB."""
    workspace_dir = tmp_path / "workspaces"
    workspace_dir.mkdir()
    # Create orphan workspace directories
    orphan1 = workspace_dir / "orphan-session-1"
    orphan2 = workspace_dir / "orphan-session-2"
    orphan1.mkdir()
    orphan2.mkdir()

    # Create a file in one of them to ensure rmtree works
    (orphan1 / "tmux.txt").write_text("some output")

    # Mock db.get_all_sessions to return empty (no known sessions)
    mock_sessions: list[MagicMock] = []

    with (
        patch("teleclaude.core.session_cleanup.db.get_all_sessions", new_callable=AsyncMock) as mock_db,
        patch("teleclaude.core.session_cleanup.OUTPUT_DIR", workspace_dir),
    ):
        mock_db.return_value = mock_sessions

        removed = await cleanup_orphan_workspaces()

    assert removed == 2
    assert not orphan1.exists()
    assert not orphan2.exists()


@pytest.mark.asyncio
async def test_cleanup_orphan_workspaces_keeps_known_sessions(tmp_path: Path):
    """Paranoid test that cleanup_orphan_workspaces keeps directories that exist in DB."""
    known_session_id = "known-session-123"
    workspace_dir = tmp_path / "workspaces"
    workspace_dir.mkdir()

    # Create workspace for known session
    known_dir = workspace_dir / known_session_id
    known_dir.mkdir()
    (known_dir / "tmux.txt").write_text("session output")

    # Create orphan workspace
    orphan_dir = workspace_dir / "orphan-session"
    orphan_dir.mkdir()

    # Mock db to return the known session
    mock_session = MagicMock()
    mock_session.session_id = known_session_id

    with (
        patch("teleclaude.core.session_cleanup.db.get_all_sessions", new_callable=AsyncMock) as mock_db,
        patch("teleclaude.core.session_cleanup.OUTPUT_DIR", workspace_dir),
    ):
        mock_db.return_value = [mock_session]

        removed = await cleanup_orphan_workspaces()

    assert removed == 1
    assert known_dir.exists()  # Should NOT be removed
    assert not orphan_dir.exists()  # Should be removed


@pytest.mark.asyncio
async def test_cleanup_orphan_workspaces_handles_missing_directory():
    """Paranoid test that cleanup_orphan_workspaces handles missing workspace directory."""
    nonexistent_path = Path("/nonexistent/workspace/path")

    with patch("teleclaude.core.session_cleanup.OUTPUT_DIR", nonexistent_path):
        removed = await cleanup_orphan_workspaces()

    assert removed == 0


@pytest.mark.asyncio
@patch("teleclaude.core.session_cleanup.subprocess.run")
@patch("teleclaude.core.session_cleanup.os.kill")
async def test_cleanup_orphan_mcp_wrappers_kills_ppid1(mock_kill, mock_run):
    """Test that orphaned MCP wrappers with PPID 1 are terminated."""
    mock_run.return_value = MagicMock(
        stdout=" 111 1 /usr/bin/python /path/bin/mcp-wrapper.py\n 222 2 /usr/bin/python /path/bin/mcp-wrapper.py\n"
    )

    killed = await cleanup_orphan_mcp_wrappers()

    assert killed == 1
    assert mock_kill.call_args == ((111, signal.SIGTERM), {})


@pytest.mark.asyncio
@patch("teleclaude.core.session_cleanup.subprocess.run")
async def test_cleanup_orphan_mcp_wrappers_noop(mock_run):
    """Test that cleanup_orphan_mcp_wrappers skips non-orphaned processes."""
    mock_run.return_value = MagicMock(stdout=" 111 2 /usr/bin/python /path/bin/mcp-wrapper.py\n")

    killed = await cleanup_orphan_mcp_wrappers()

    assert killed == 0


@pytest.mark.asyncio
async def test_terminate_session_deletes_db_and_resources():
    """Paranoid test that terminate_session deletes resources and DB record via observable effects."""
    mock_session = MagicMock()
    mock_session.session_id = "session-123"
    mock_session.tmux_session_name = "tc_session"
    mock_session.last_input_origin = "telegram"

    adapter_client = MagicMock()

    with (
        patch("teleclaude.core.session_cleanup.db.get_session", new_callable=AsyncMock) as mock_get,
        patch("teleclaude.core.session_cleanup.db.delete_session", new_callable=AsyncMock) as mock_delete,
        patch("teleclaude.core.session_cleanup.tmux_bridge.kill_session", new_callable=AsyncMock) as mock_kill,
        patch("teleclaude.core.session_cleanup.cleanup_session_resources", new_callable=AsyncMock) as mock_cleanup,
    ):
        mock_get.return_value = mock_session
        mock_kill.return_value = True

        result = await session_cleanup.terminate_session(
            "session-123",
            adapter_client,
            reason="test",
            session=mock_session,
            delete_db=True,
        )

    assert result is True
    assert mock_kill.call_args == (("tc_session",), {})
    assert mock_cleanup.call_args == ((mock_session, adapter_client), {"delete_channel": True})
    assert mock_delete.call_args == (("session-123",), {})


@pytest.mark.asyncio
async def test_terminate_session_kills_tmux_for_terminal_origin():
    """Test that terminal-origin sessions use tmux kill on termination."""
    mock_session = MagicMock()
    mock_session.session_id = "session-456"
    mock_session.tmux_session_name = "terminal:deadbeef"
    mock_session.last_input_origin = "terminal"

    adapter_client = MagicMock()

    with (
        patch("teleclaude.core.session_cleanup.db.get_session", new_callable=AsyncMock) as mock_get,
        patch("teleclaude.core.session_cleanup.db.delete_session", new_callable=AsyncMock) as mock_delete,
        patch("teleclaude.core.session_cleanup.tmux_bridge.kill_session", new_callable=AsyncMock) as mock_kill,
        patch("teleclaude.core.session_cleanup.cleanup_session_resources", new_callable=AsyncMock) as mock_cleanup,
    ):
        mock_get.return_value = mock_session

        result = await session_cleanup.terminate_session(
            "session-456",
            adapter_client,
            reason="test",
            session=mock_session,
            delete_db=True,
        )

    assert result is True
    assert mock_kill.call_args == (("terminal:deadbeef",), {})
    assert mock_cleanup.call_args == ((mock_session, adapter_client), {"delete_channel": True})
    assert mock_delete.call_args == (("session-456",), {})


@pytest.mark.asyncio
async def test_cleanup_session_resources_uses_to_thread_for_rmtree(monkeypatch, tmp_path: Path) -> None:
    """Test that cleanup_session_resources offloads rmtree via asyncio.to_thread."""
    called = {}

    async def fake_to_thread(func, *args, **kwargs):
        called["func"] = func
        called["args"] = args
        return func(*args, **kwargs)

    async def noop_async(*_args, **_kwargs):
        return None

    (tmp_path / "file.txt").write_text("data")

    monkeypatch.setattr(session_cleanup.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(session_cleanup, "get_session_output_dir", lambda _sid: tmp_path)
    monkeypatch.setattr("teleclaude.core.session_cleanup.pop_listeners", AsyncMock(return_value=[]))
    monkeypatch.setattr("teleclaude.core.session_cleanup.cleanup_caller_listeners", AsyncMock(return_value=0))
    adapter_client = SimpleNamespace(delete_channel=AsyncMock())
    session = SimpleNamespace(session_id="sess-1")

    await session_cleanup.cleanup_session_resources(session, adapter_client)

    assert adapter_client.delete_channel.call_args == ((session,), {})
    assert called["func"] is shutil.rmtree
    assert called["args"][0] == tmp_path
    assert not tmp_path.exists()


@pytest.mark.asyncio
async def test_emit_recently_closed_session_events_only_replays_window() -> None:
    """Replay session_closed only for sessions that closed within configured window."""
    fixed_now = datetime(2026, 1, 14, 12, 0, 0, tzinfo=timezone.utc)

    recent_closed = SimpleNamespace(
        session_id="recent",
        closed_at=fixed_now - timedelta(hours=1),
    )
    old_closed = SimpleNamespace(
        session_id="old",
        closed_at=fixed_now - timedelta(hours=24),
    )
    active_session = SimpleNamespace(
        session_id="active",
        closed_at=None,
    )

    with (
        patch("teleclaude.core.session_cleanup.datetime") as mock_datetime,
        patch(
            "teleclaude.core.session_cleanup.db.list_sessions",
            new=AsyncMock(return_value=[recent_closed, old_closed, active_session]),
        ),
        patch("teleclaude.core.session_cleanup.event_bus.emit") as mock_emit,
    ):
        mock_datetime.now.return_value = fixed_now

        emitted = await emit_recently_closed_session_events(hours=12)

    assert emitted == 1
    assert mock_emit.call_count == 1
    emitted_event, emitted_ctx = mock_emit.call_args.args  # type: ignore[misc]
    assert emitted_event == TeleClaudeEvents.SESSION_CLOSED
    assert emitted_ctx.session_id == "recent"
