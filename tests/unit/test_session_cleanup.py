"""Unit tests for session cleanup utilities."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.session_cleanup import cleanup_orphan_workspaces


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
        patch("teleclaude.core.session_utils.OUTPUT_DIR", tmp_path),
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

    with (
        patch("teleclaude.core.session_cleanup.db.get_all_sessions", new_callable=AsyncMock) as mock_db,
        patch("teleclaude.core.session_utils.OUTPUT_DIR", tmp_path),
    ):
        mock_db.return_value = [mock_session]

        removed = await cleanup_orphan_workspaces()

    assert removed == 1
    assert known_dir.exists()  # Should NOT be removed
    assert not orphan_dir.exists()  # Should be removed


@pytest.mark.asyncio
async def test_cleanup_orphan_workspaces_handles_missing_directory():
    """Test that cleanup_orphan_workspaces handles missing workspace directory."""
    nonexistent_path = Path("/nonexistent/workspace/path")

    with patch("teleclaude.core.session_utils.OUTPUT_DIR", nonexistent_path):
        removed = await cleanup_orphan_workspaces()

    assert removed == 0


@pytest.mark.skip(reason="TODO: Implement test")
async def test_cleanup_stale_session_detects_missing_tmux():
    """Test that cleanup_stale_session detects when tmux session is gone.

    TODO: Test stale detection:
    - Mock db.get_session (active session)
    - Mock terminal_bridge.session_exists to return False
    - Verify cleanup performed
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_cleanup_stale_session_skips_healthy_session():
    """Test that cleanup_stale_session skips healthy sessions.

    TODO: Test healthy session:
    - Mock db.get_session (active session)
    - Mock terminal_bridge.session_exists to return True
    - Verify no cleanup performed
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_cleanup_stale_session_skips_already_closed():
    """Test that cleanup_stale_session skips already closed sessions.

    TODO: Test closed session:
    - Mock db.get_session (closed=True)
    - Verify no cleanup performed
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_cleanup_stale_session_marks_as_closed():
    """Test that cleanup_stale_session marks session as closed in DB.

    TODO: Test DB update:
    - Mock stale session
    - Verify db.update_session called with closed=True
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_cleanup_stale_session_deletes_channel():
    """Test that cleanup_stale_session deletes channel.

    TODO: Test channel deletion:
    - Mock stale session
    - Verify adapter_client.delete_channel called
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_cleanup_stale_session_deletes_output_file():
    """Test that cleanup_stale_session deletes output file.

    TODO: Test file deletion:
    - Create temp output file
    - Mock stale session
    - Verify file deleted
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_cleanup_stale_session_handles_channel_deletion_failure():
    """Test that cleanup continues if channel deletion fails.

    TODO: Test error handling:
    - Mock adapter_client.delete_channel to raise exception
    - Verify cleanup continues
    - Verify warning logged
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_cleanup_all_stale_sessions_processes_all():
    """Test that cleanup_all_stale_sessions processes all active sessions.

    TODO: Test batch cleanup:
    - Mock db.get_active_sessions with multiple sessions
    - Mock some as stale, some as healthy
    - Verify correct count returned
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_cleanup_all_stale_sessions_handles_empty_list():
    """Test that cleanup_all_stale_sessions handles no active sessions.

    TODO: Test edge case:
    - Mock db.get_active_sessions to return []
    - Verify returns 0
    - Verify no errors
    """
