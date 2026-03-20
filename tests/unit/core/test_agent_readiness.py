from itertools import chain, repeat
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.agent_readiness import wait_for_agent_ready
from teleclaude.core.agents import AgentName
from teleclaude.core.models._session import Session


@pytest.fixture
def mock_session():
    session = AsyncMock(spec=Session)
    session.tmux_session_name = "tc_test"
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_name", [AgentName.CLAUDE, AgentName.GEMINI, AgentName.CODEX])
async def test_wait_for_agent_ready_settle_then_marker_success(mock_session, agent_name):
    """Test successful readiness: first settle, then marker is already there."""
    # SC-1: Marker must be resolved from AgentName metadata
    marker = agent_name.prompt_marker
    with patch("teleclaude.core.agent_readiness.tmux_bridge.capture_pane", create=True) as mock_capture:
        final_output = f"loading... done\n{marker}"
        mock_capture.side_effect = chain(
            [
                "loading...",
                "loading... done\n",
                final_output,
                final_output,
            ],
            repeat(final_output),
        )

        ready, tail = await wait_for_agent_ready(
            agent_name=agent_name, session=mock_session, timeout_s=1.0, quiet_s=0.1, poll_interval_s=0.05
        )

        assert ready is True
        assert marker in tail


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_name", [AgentName.CLAUDE, AgentName.GEMINI, AgentName.CODEX])
async def test_wait_for_agent_ready_late_marker_re_settle(mock_session, agent_name):
    """Test SC-6: marker appears after initial settle, must re-settle."""
    marker = agent_name.prompt_marker
    with patch("teleclaude.core.agent_readiness.tmux_bridge.capture_pane", create=True) as mock_capture:
        final_output = f"loading... done\n{marker}"
        mock_capture.side_effect = chain(
            [
                "loading...",
                "loading... done\n",
                "loading... done\n",
                "loading... done\n",
                final_output,
                final_output,
                final_output,
            ],
            repeat(final_output),
        )

        ready, tail = await wait_for_agent_ready(
            agent_name=agent_name, session=mock_session, timeout_s=2.0, quiet_s=0.1, poll_interval_s=0.05
        )

        assert ready is True
        assert marker in tail
        # Ensure it polled through both settle windows
        assert mock_capture.call_count >= 7


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_name", [AgentName.CLAUDE, AgentName.GEMINI, AgentName.CODEX])
async def test_wait_for_agent_ready_timeout(mock_session, agent_name):
    """Test that it returns False on timeout."""
    with patch("teleclaude.core.agent_readiness.tmux_bridge.capture_pane", create=True) as mock_capture:
        mock_capture.return_value = "still loading..."

        ready, tail = await wait_for_agent_ready(
            agent_name=agent_name, session=mock_session, timeout_s=0.2, quiet_s=0.1, poll_interval_s=0.05
        )

        assert ready is False
        assert "still loading..." in tail


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_name", [AgentName.CLAUDE, AgentName.GEMINI, AgentName.CODEX])
async def test_wait_for_agent_ready_fails_when_marker_never_appears(mock_session, agent_name):
    """Test that it returns False if it stabilizes but marker never appears."""
    marker = agent_name.prompt_marker
    with patch("teleclaude.core.agent_readiness.tmux_bridge.capture_pane", create=True) as mock_capture:
        mock_capture.side_effect = chain(
            [
                "loading...",
                "loading... done\n",
                "loading... done\n",
                "loading... done\n",
                "loading... done\n",
                "loading... done\n",
            ],
            repeat("loading... done\n"),
        )

        ready, tail = await wait_for_agent_ready(
            agent_name=agent_name, session=mock_session, timeout_s=0.5, quiet_s=0.1, poll_interval_s=0.05
        )

        assert ready is False
        assert marker not in tail
