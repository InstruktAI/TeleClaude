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


# Tests for session title building functions


def test_build_computer_prefix_with_agent():
    """Test build_computer_prefix with agent info returns Agent-mode@Computer."""
    from teleclaude.core.session_utils import build_computer_prefix

    result = build_computer_prefix("MozMini", agent_name="claude", thinking_mode="slow")
    assert result == "Claude-slow@MozMini"


def test_build_computer_prefix_without_agent():
    """Test build_computer_prefix without agent info returns $Computer."""
    from teleclaude.core.session_utils import build_computer_prefix

    result = build_computer_prefix("MozMini")
    assert result == "$MozMini"


def test_build_computer_prefix_capitalizes_agent():
    """Test build_computer_prefix capitalizes agent name."""
    from teleclaude.core.session_utils import build_computer_prefix

    result = build_computer_prefix("RasPi", agent_name="gemini", thinking_mode="fast")
    assert result == "Gemini-fast@RasPi"


def test_build_session_title_human_session():
    """Test build_session_title for human-initiated session."""
    from teleclaude.core.session_utils import build_session_title

    result = build_session_title(
        computer_name="MozMini",
        short_project="apps/TeleClaude",
        description="New session",
    )
    assert result == "$MozMini[apps/TeleClaude] - New session"


def test_build_session_title_human_session_with_agent():
    """Test build_session_title for human session with known agent."""
    from teleclaude.core.session_utils import build_session_title

    result = build_session_title(
        computer_name="MozMini",
        short_project="apps/TeleClaude",
        description="Debug auth flow",
        agent_name="claude",
        thinking_mode="slow",
    )
    assert result == "Claude-slow@MozMini[apps/TeleClaude] - Debug auth flow"


def test_build_session_title_ai_to_ai_session():
    """Test build_session_title for AI-to-AI session."""
    from teleclaude.core.session_utils import build_session_title

    result = build_session_title(
        computer_name="RasPi",
        short_project="apps/TeleClaude",
        description="New session",
        initiator_computer="MozBook",
    )
    assert result == "$MozBook > $RasPi[apps/TeleClaude] - New session"


def test_build_session_title_ai_to_ai_with_agents():
    """Test build_session_title for AI-to-AI session with both agents known."""
    from teleclaude.core.session_utils import build_session_title

    result = build_session_title(
        computer_name="RasPi",
        short_project="apps/TeleClaude",
        description="Build feature",
        initiator_computer="MozBook",
        agent_name="gemini",
        thinking_mode="med",
        initiator_agent="claude",
        initiator_mode="slow",
    )
    assert result == "Claude-slow@MozBook > Gemini-med@RasPi[apps/TeleClaude] - Build feature"


def test_parse_session_title_old_format():
    """Test parse_session_title with old $Computer format."""
    from teleclaude.core.session_utils import parse_session_title

    prefix, description = parse_session_title("$MozMini[apps/TeleClaude] - Debug auth flow")
    assert prefix == "$MozMini[apps/TeleClaude] - "
    assert description == "Debug auth flow"


def test_parse_session_title_new_format():
    """Test parse_session_title with new Agent-mode@Computer format."""
    from teleclaude.core.session_utils import parse_session_title

    prefix, description = parse_session_title("Claude-slow@MozMini[apps/TeleClaude] - Debug auth")
    assert prefix == "Claude-slow@MozMini[apps/TeleClaude] - "
    assert description == "Debug auth"


def test_parse_session_title_ai_to_ai():
    """Test parse_session_title with AI-to-AI format."""
    from teleclaude.core.session_utils import parse_session_title

    prefix, description = parse_session_title("$MozBook > $RasPi[apps/TeleClaude] - New session")
    assert prefix == "$MozBook > $RasPi[apps/TeleClaude] - "
    assert description == "New session"


def test_parse_session_title_invalid():
    """Test parse_session_title with invalid format returns None."""
    from teleclaude.core.session_utils import parse_session_title

    prefix, description = parse_session_title("Invalid title format")
    assert prefix is None
    assert description is None


def test_update_title_with_agent():
    """Test update_title_with_agent replaces $Computer with Agent-mode@Computer."""
    from teleclaude.core.session_utils import update_title_with_agent

    result = update_title_with_agent(
        title="$MozMini[apps/TeleClaude] - New session",
        agent_name="claude",
        thinking_mode="slow",
        computer_name="MozMini",
    )
    assert result == "Claude-slow@MozMini[apps/TeleClaude] - New session"


def test_update_title_with_agent_ai_to_ai():
    """Test update_title_with_agent only replaces target computer prefix."""
    from teleclaude.core.session_utils import update_title_with_agent

    result = update_title_with_agent(
        title="$MozBook > $RasPi[apps/TeleClaude] - Build feature",
        agent_name="gemini",
        thinking_mode="med",
        computer_name="RasPi",
    )
    # Should only replace target computer ($RasPi), not initiator ($MozBook)
    assert result == "$MozBook > Gemini-med@RasPi[apps/TeleClaude] - Build feature"


def test_update_title_with_agent_no_match():
    """Test update_title_with_agent returns None when computer not found."""
    from teleclaude.core.session_utils import update_title_with_agent

    result = update_title_with_agent(
        title="$OtherComputer[apps/TeleClaude] - New session",
        agent_name="claude",
        thinking_mode="slow",
        computer_name="MozMini",  # Not in title
    )
    assert result is None
