"""Unit tests for session cleanup utilities."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.session_cleanup import (
    cleanup_all_stale_sessions,
    cleanup_orphan_workspaces,
    cleanup_stale_session,
)


@pytest.mark.asyncio
async def test_cleanup_orphan_workspaces_removes_orphans(tmp_path: Path):
    """Test that cleanup_orphan_workspaces removes directories not in DB."""
    # Create orphan workspace directories
    orphan1 = tmp_path / "orphan-session-1"
    orphan2 = tmp_path / "orphan-session-2"
    orphan1.mkdir()
    orphan2.mkdir()

    # Create a file in one of them to ensure rmtree works
    (orphan1 / "tmux.txt").write_text("some output")

    # Mock db.get_all_sessions to return empty (no known sessions)
    mock_sessions: list[MagicMock] = []

    with (
        patch("teleclaude.core.session_cleanup.db.get_all_sessions", new_callable=AsyncMock) as mock_db,
        patch("teleclaude.core.session_cleanup.OUTPUT_DIR", tmp_path),
    ):
        mock_db.return_value = mock_sessions

        removed = await cleanup_orphan_workspaces()

    assert removed == 2
    assert not orphan1.exists()
    assert not orphan2.exists()


@pytest.mark.asyncio
async def test_cleanup_orphan_workspaces_keeps_known_sessions(tmp_path: Path):
    """Test that cleanup_orphan_workspaces keeps directories that exist in DB."""
    known_session_id = "known-session-123"

    # Create workspace for known session
    known_dir = tmp_path / known_session_id
    known_dir.mkdir()
    (known_dir / "tmux.txt").write_text("session output")

    # Create orphan workspace
    orphan_dir = tmp_path / "orphan-session"
    orphan_dir.mkdir()

    # Mock db to return the known session
    mock_session = MagicMock()
    mock_session.session_id = known_session_id
    mock_session.closed = False

    with (
        patch("teleclaude.core.session_cleanup.db.get_all_sessions", new_callable=AsyncMock) as mock_db,
        patch("teleclaude.core.session_cleanup.OUTPUT_DIR", tmp_path),
    ):
        mock_db.return_value = [mock_session]

        removed = await cleanup_orphan_workspaces()

    assert removed == 1
    assert known_dir.exists()  # Should NOT be removed
    assert not orphan_dir.exists()  # Should be removed


@pytest.mark.asyncio
async def test_cleanup_orphan_workspaces_removes_closed_sessions(tmp_path: Path):
    """Closed sessions should not keep workspace directories."""
    closed_session_id = "closed-session-123"

    closed_dir = tmp_path / closed_session_id
    closed_dir.mkdir()
    (closed_dir / "tmux.txt").write_text("closed output")

    mock_session = MagicMock()
    mock_session.session_id = closed_session_id
    mock_session.closed = True

    with (
        patch("teleclaude.core.session_cleanup.db.get_all_sessions", new_callable=AsyncMock) as mock_db,
        patch("teleclaude.core.session_cleanup.OUTPUT_DIR", tmp_path),
    ):
        mock_db.return_value = [mock_session]

        removed = await cleanup_orphan_workspaces()

    assert removed == 1
    assert not closed_dir.exists()


@pytest.mark.asyncio
async def test_cleanup_orphan_workspaces_handles_missing_directory():
    """Test that cleanup_orphan_workspaces handles missing workspace directory."""
    nonexistent_path = Path("/nonexistent/workspace/path")

    with patch("teleclaude.core.session_cleanup.OUTPUT_DIR", nonexistent_path):
        removed = await cleanup_orphan_workspaces()

    assert removed == 0


@pytest.mark.asyncio
async def test_cleanup_stale_session_detects_missing_tmux():
    """Test that cleanup_stale_session detects when tmux session is gone."""
    mock_session = MagicMock()
    mock_session.session_id = "stale-session-123"
    mock_session.tmux_session_name = "tc_stale"
    mock_session.closed = False

    mock_adapter_client = MagicMock()
    mock_adapter_client.delete_channel = AsyncMock()

    with (
        patch("teleclaude.core.session_cleanup.db.get_session", new_callable=AsyncMock) as mock_get,
        patch("teleclaude.core.session_cleanup.db.update_session", new_callable=AsyncMock) as mock_update,
        patch("teleclaude.core.session_cleanup.db.clear_pending_deletions", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.db.update_ux_state", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.terminal_bridge.session_exists", new_callable=AsyncMock) as mock_exists,
        patch("teleclaude.core.session_cleanup.get_session_output_dir") as mock_output_dir,
    ):
        mock_get.return_value = mock_session
        mock_exists.return_value = False  # tmux session is gone
        mock_output_dir.return_value = MagicMock(exists=MagicMock(return_value=False))

        result = await cleanup_stale_session("stale-session-123", mock_adapter_client)

    assert result is True
    mock_update.assert_called_once_with("stale-session-123", closed=True)
    mock_adapter_client.delete_channel.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_stale_session_skips_healthy_session():
    """Test that cleanup_stale_session skips healthy sessions."""
    mock_session = MagicMock()
    mock_session.session_id = "healthy-session-123"
    mock_session.tmux_session_name = "tc_healthy"
    mock_session.closed = False

    mock_adapter_client = MagicMock()

    with (
        patch("teleclaude.core.session_cleanup.db.get_session", new_callable=AsyncMock) as mock_get,
        patch("teleclaude.core.session_cleanup.terminal_bridge.session_exists", new_callable=AsyncMock) as mock_exists,
    ):
        mock_get.return_value = mock_session
        mock_exists.return_value = True  # tmux session exists

        result = await cleanup_stale_session("healthy-session-123", mock_adapter_client)

    assert result is False


@pytest.mark.asyncio
async def test_cleanup_stale_session_skips_already_closed():
    """Test that cleanup_stale_session skips already closed sessions."""
    mock_session = MagicMock()
    mock_session.session_id = "closed-session-123"
    mock_session.closed = True

    mock_adapter_client = MagicMock()

    with patch("teleclaude.core.session_cleanup.db.get_session", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_session

        result = await cleanup_stale_session("closed-session-123", mock_adapter_client)

    assert result is False


@pytest.mark.asyncio
async def test_cleanup_stale_session_marks_as_closed():
    """Test that cleanup_stale_session marks session as closed in DB."""
    mock_session = MagicMock()
    mock_session.session_id = "stale-session-123"
    mock_session.tmux_session_name = "tc_stale"
    mock_session.closed = False

    mock_adapter_client = MagicMock()
    mock_adapter_client.delete_channel = AsyncMock()

    with (
        patch("teleclaude.core.session_cleanup.db.get_session", new_callable=AsyncMock) as mock_get,
        patch("teleclaude.core.session_cleanup.db.update_session", new_callable=AsyncMock) as mock_update,
        patch("teleclaude.core.session_cleanup.db.clear_pending_deletions", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.db.update_ux_state", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.terminal_bridge.session_exists", new_callable=AsyncMock) as mock_exists,
        patch("teleclaude.core.session_cleanup.get_session_output_dir") as mock_output_dir,
    ):
        mock_get.return_value = mock_session
        mock_exists.return_value = False
        mock_output_dir.return_value = MagicMock(exists=MagicMock(return_value=False))

        await cleanup_stale_session("stale-session-123", mock_adapter_client)

    mock_update.assert_called_once_with("stale-session-123", closed=True)


@pytest.mark.asyncio
async def test_cleanup_stale_session_deletes_channel():
    """Test that cleanup_stale_session deletes channel."""
    mock_session = MagicMock()
    mock_session.session_id = "stale-session-123"
    mock_session.tmux_session_name = "tc_stale"
    mock_session.closed = False

    mock_adapter_client = MagicMock()
    mock_adapter_client.delete_channel = AsyncMock()

    with (
        patch("teleclaude.core.session_cleanup.db.get_session", new_callable=AsyncMock) as mock_get,
        patch("teleclaude.core.session_cleanup.db.update_session", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.db.clear_pending_deletions", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.db.update_ux_state", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.terminal_bridge.session_exists", new_callable=AsyncMock) as mock_exists,
        patch("teleclaude.core.session_cleanup.get_session_output_dir") as mock_output_dir,
    ):
        mock_get.return_value = mock_session
        mock_exists.return_value = False
        mock_output_dir.return_value = MagicMock(exists=MagicMock(return_value=False))

        await cleanup_stale_session("stale-session-123", mock_adapter_client)

    mock_adapter_client.delete_channel.assert_called_once_with(mock_session)


@pytest.mark.asyncio
async def test_cleanup_stale_session_deletes_output_file(tmp_path: Path):
    """Test that cleanup_stale_session deletes output file."""
    session_id = "stale-session-123"
    workspace_dir = tmp_path / session_id
    workspace_dir.mkdir()
    (workspace_dir / "tmux.txt").write_text("session output")

    mock_session = MagicMock()
    mock_session.session_id = session_id
    mock_session.tmux_session_name = "tc_stale"
    mock_session.closed = False

    mock_adapter_client = MagicMock()
    mock_adapter_client.delete_channel = AsyncMock()

    with (
        patch("teleclaude.core.session_cleanup.db.get_session", new_callable=AsyncMock) as mock_get,
        patch("teleclaude.core.session_cleanup.db.update_session", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.db.clear_pending_deletions", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.db.update_ux_state", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.terminal_bridge.session_exists", new_callable=AsyncMock) as mock_exists,
        patch("teleclaude.core.session_cleanup.get_session_output_dir") as mock_output_dir,
    ):
        mock_get.return_value = mock_session
        mock_exists.return_value = False
        mock_output_dir.return_value = workspace_dir

        await cleanup_stale_session(session_id, mock_adapter_client)

    assert not workspace_dir.exists()


@pytest.mark.asyncio
async def test_cleanup_stale_session_handles_channel_deletion_failure():
    """Test that cleanup continues if channel deletion fails."""
    mock_session = MagicMock()
    mock_session.session_id = "stale-session-123"
    mock_session.tmux_session_name = "tc_stale"
    mock_session.closed = False

    mock_adapter_client = MagicMock()
    mock_adapter_client.delete_channel = AsyncMock(side_effect=Exception("Channel deletion failed"))

    with (
        patch("teleclaude.core.session_cleanup.db.get_session", new_callable=AsyncMock) as mock_get,
        patch("teleclaude.core.session_cleanup.db.update_session", new_callable=AsyncMock) as mock_update,
        patch("teleclaude.core.session_cleanup.db.clear_pending_deletions", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.db.update_ux_state", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.terminal_bridge.session_exists", new_callable=AsyncMock) as mock_exists,
        patch("teleclaude.core.session_cleanup.get_session_output_dir") as mock_output_dir,
    ):
        mock_get.return_value = mock_session
        mock_exists.return_value = False
        mock_output_dir.return_value = MagicMock(exists=MagicMock(return_value=False))

        # Should not raise, cleanup continues
        result = await cleanup_stale_session("stale-session-123", mock_adapter_client)

    assert result is True
    mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_all_stale_sessions_processes_all():
    """Test that cleanup_all_stale_sessions processes all active sessions."""
    # Create mock sessions - 2 stale, 1 healthy
    mock_sessions = []
    for i in range(3):
        s = MagicMock()
        s.session_id = f"session-{i}"
        s.tmux_session_name = f"tc_session_{i}"
        s.closed = False
        mock_sessions.append(s)

    mock_adapter_client = MagicMock()
    mock_adapter_client.delete_channel = AsyncMock()

    # Track which sessions session_exists returns False for (stale)
    stale_sessions = {"tc_session_0", "tc_session_2"}

    async def mock_session_exists(name):
        return name not in stale_sessions

    with (
        patch("teleclaude.core.session_cleanup.db.get_active_sessions", new_callable=AsyncMock) as mock_get_active,
        patch("teleclaude.core.session_cleanup.db.get_session", new_callable=AsyncMock) as mock_get,
        patch("teleclaude.core.session_cleanup.db.update_session", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.db.clear_pending_deletions", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.db.update_ux_state", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.terminal_bridge.session_exists", side_effect=mock_session_exists),
        patch("teleclaude.core.session_cleanup.get_session_output_dir") as mock_output_dir,
    ):
        mock_get_active.return_value = mock_sessions
        mock_get.side_effect = lambda sid: next((s for s in mock_sessions if s.session_id == sid), None)
        mock_output_dir.return_value = MagicMock(exists=MagicMock(return_value=False))

        count = await cleanup_all_stale_sessions(mock_adapter_client)

    assert count == 2  # 2 stale sessions cleaned up


@pytest.mark.asyncio
async def test_cleanup_all_stale_sessions_handles_empty_list():
    """Test that cleanup_all_stale_sessions handles no active sessions."""
    mock_adapter_client = MagicMock()

    with patch("teleclaude.core.session_cleanup.db.get_active_sessions", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = []

        count = await cleanup_all_stale_sessions(mock_adapter_client)

    assert count == 0
