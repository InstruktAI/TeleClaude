"""Unit tests for session utility functions."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_ensure_unique_title_returns_base_when_unique():
    """Test that ensure_unique_title returns base title when unique."""
    from teleclaude.core.session_utils import ensure_unique_title

    # Mock db.list_sessions to return no sessions
    with patch("teleclaude.core.session_utils.db") as mock_db:
        mock_db.list_sessions = AsyncMock(return_value=[])

        result = await ensure_unique_title("My Unique Title")

        assert result == "My Unique Title"
        mock_db.list_sessions.assert_called_once_with(closed=False)


@pytest.mark.asyncio
async def test_ensure_unique_title_appends_counter_on_collision():
    """Test that ensure_unique_title appends (2) on collision."""
    from teleclaude.core.session_utils import ensure_unique_title

    # Create mock session with matching title
    mock_session = MagicMock()
    mock_session.title = "Duplicate Title"

    with patch("teleclaude.core.session_utils.db") as mock_db:
        mock_db.list_sessions = AsyncMock(return_value=[mock_session])

        result = await ensure_unique_title("Duplicate Title")

        assert result == "Duplicate Title (2)"


@pytest.mark.asyncio
async def test_ensure_unique_title_increments_counter():
    """Test that ensure_unique_title increments counter for multiple collisions."""
    from teleclaude.core.session_utils import ensure_unique_title

    # Create mock sessions with title and numbered versions
    mock_sessions = []
    for title in ["Foo", "Foo (2)", "Foo (3)"]:
        mock_session = MagicMock()
        mock_session.title = title
        mock_sessions.append(mock_session)

    with patch("teleclaude.core.session_utils.db") as mock_db:
        mock_db.list_sessions = AsyncMock(return_value=mock_sessions)

        result = await ensure_unique_title("Foo")

        # Should skip (2) and (3), return (4)
        assert result == "Foo (4)"


@pytest.mark.asyncio
async def test_ensure_unique_title_handles_empty_sessions():
    """Test that ensure_unique_title handles empty session list."""
    from teleclaude.core.session_utils import ensure_unique_title

    with patch("teleclaude.core.session_utils.db") as mock_db:
        mock_db.list_sessions = AsyncMock(return_value=[])

        result = await ensure_unique_title("Empty List Title")

        assert result == "Empty List Title"


def test_get_output_file_returns_correct_path():
    """Test that get_output_file returns correct path format."""
    from teleclaude.core import session_utils

    # Use temporary directory to avoid affecting real workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        # Patch OUTPUT_DIR to use temp directory
        with patch.object(session_utils, "OUTPUT_DIR", Path(tmpdir)):
            result = session_utils.get_output_file("test-session-123")

            # Verify path format: {tmpdir}/test-session-123/tmux.txt
            assert result == Path(tmpdir) / "test-session-123" / "tmux.txt"
            assert result.exists()


def test_get_output_file_creates_directory():
    """Test that get_output_file creates workspace directory."""
    from teleclaude.core import session_utils

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "workspace"
        # Directory should NOT exist yet
        assert not output_dir.exists()

        with patch.object(session_utils, "OUTPUT_DIR", output_dir):
            result = session_utils.get_output_file("new-session-456")

            # Verify directory was created
            assert output_dir.exists()
            assert (output_dir / "new-session-456").is_dir()
            # Verify file was created
            assert result.exists()
            assert result.name == "tmux.txt"
