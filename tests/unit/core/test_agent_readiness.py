"""Tests for agent readiness detection."""

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


def _prompt_output(agent_name: AgentName) -> str:
    if agent_name == AgentName.CLAUDE:
        return "\u276f"
    if agent_name == AgentName.GEMINI:
        return "Type your message or @path/to/file"
    return "\x1b[1m\u203a\x1b[0m \x1b[2mImplement {feature}\x1b[0m"


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_name", [AgentName.CLAUDE, AgentName.GEMINI, AgentName.CODEX])
async def test_wait_for_agent_ready_settle_then_marker_success(mock_session, agent_name):
    """Test successful readiness: first settle, then marker is already there."""
    prompt = _prompt_output(agent_name)
    with patch("teleclaude.core.agent_readiness.tmux_bridge.capture_pane", create=True) as mock_capture:
        final_output = f"loading... done\n{prompt}"
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
        assert "loading... done" in tail
        assert "Implement {feature}" in tail or prompt in tail


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_name", [AgentName.CLAUDE, AgentName.GEMINI, AgentName.CODEX])
async def test_wait_for_agent_ready_late_marker_re_settle(mock_session, agent_name):
    """Test SC-6: marker appears after initial settle, must re-settle."""
    prompt = _prompt_output(agent_name)
    with patch("teleclaude.core.agent_readiness.tmux_bridge.capture_pane", create=True) as mock_capture:
        final_output = f"loading... done\n{prompt}"
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
        assert "loading... done" in tail
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
        assert "loading... done" in tail


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_name", [AgentName.CLAUDE, AgentName.GEMINI, AgentName.CODEX])
async def test_wait_for_agent_ready_requires_pre_prompt_churn_to_settle(mock_session, agent_name):
    """Prompt visibility alone is insufficient while text above it is still changing."""
    prompt = _prompt_output(agent_name)
    with patch("teleclaude.core.agent_readiness.tmux_bridge.capture_pane", create=True) as mock_capture:
        final_output = f"mcp settle complete\n{prompt}"
        mock_capture.side_effect = chain(
            [
                f"mcp settle 1\n{prompt}",
                f"mcp settle 2\n{prompt}",
                final_output,
                final_output,
                final_output,
            ],
            repeat(final_output),
        )

        ready, tail = await wait_for_agent_ready(
            agent_name=agent_name, session=mock_session, timeout_s=1.0, quiet_s=0.1, poll_interval_s=0.05
        )

        assert ready is True
        assert "mcp settle complete" in tail
        assert mock_capture.call_count >= 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("agent_name", "footer_1", "footer_2"),
    [
        (AgentName.CLAUDE, "15s elapsed", "16s elapsed"),
        (AgentName.GEMINI, "15s elapsed", "16s elapsed"),
        (AgentName.CODEX, "? for shortcuts", "? for shortcuts and commands"),
    ],
)
async def test_wait_for_agent_ready_ignores_below_prompt_churn(mock_session, agent_name, footer_1, footer_2):
    """Changes below the prompt should not reset quiet detection."""
    prompt = _prompt_output(agent_name)
    stable_prefix = "mcp settle complete"
    with patch("teleclaude.core.agent_readiness.tmux_bridge.capture_pane", create=True) as mock_capture:
        final_output = f"{stable_prefix}\n{prompt}\n{footer_2}"
        mock_capture.side_effect = chain(
            [
                f"{stable_prefix}\n{prompt}\n{footer_1}",
                final_output,
                final_output,
                final_output,
            ],
            repeat(final_output),
        )

        ready, tail = await wait_for_agent_ready(
            agent_name=agent_name, session=mock_session, timeout_s=1.0, quiet_s=0.1, poll_interval_s=0.05
        )

        assert ready is True
        assert stable_prefix in tail
