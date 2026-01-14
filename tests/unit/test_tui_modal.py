"""Unit tests for StartSessionModal."""

# type: ignore - test uses mock objects

from unittest.mock import MagicMock

import pytest

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.widgets.modal import StartSessionModal


@pytest.fixture
def mock_api():
    """Create mock API client."""
    return MagicMock()


def test_modal_init_defaults_to_first_available_agent(mock_api):
    """Test modal selects first available agent on init."""
    agent_availability = {
        "claude": AgentAvailabilityInfo(
            agent="claude",
            available=False,
            unavailable_until=None,
            reason="rate_limited",
        ),
        "gemini": AgentAvailabilityInfo(
            agent="gemini",
            available=True,
            unavailable_until=None,
            reason=None,
        ),
        "codex": AgentAvailabilityInfo(
            agent="codex",
            available=True,
            unavailable_until=None,
            reason=None,
        ),
    }

    modal = StartSessionModal(
        computer="local",
        project_path="/home/user/project",
        api=mock_api,
        agent_availability=agent_availability,
    )

    # Should skip claude (unavailable) and select gemini (index 1)
    assert modal.selected_agent == 1


def test_modal_init_defaults_to_slow_mode(mock_api):
    """Test modal defaults to slow mode."""
    agent_availability = {
        "claude": AgentAvailabilityInfo(
            agent="claude",
            available=True,
            unavailable_until=None,
            reason=None,
        )
    }

    modal = StartSessionModal(
        computer="local",
        project_path="/home/user/project",
        api=mock_api,
        agent_availability=agent_availability,
    )

    assert modal.selected_mode == 1  # slow mode


def test_modal_is_agent_available(mock_api):
    """Test _is_agent_available checks availability correctly."""
    agent_availability = {
        "claude": AgentAvailabilityInfo(
            agent="claude",
            available=True,
            unavailable_until=None,
            reason=None,
        ),
        "gemini": AgentAvailabilityInfo(
            agent="gemini",
            available=False,
            unavailable_until=None,
            reason="rate_limited",
        ),
        # Codex missing from map = treated as unavailable
    }

    modal = StartSessionModal(
        computer="local",
        project_path="/home/user/project",
        api=mock_api,
        agent_availability=agent_availability,
    )

    assert modal._is_agent_available("claude") is True
    assert modal._is_agent_available("gemini") is False
    assert modal._is_agent_available("codex") is False


def test_modal_get_available_agents(mock_api):
    """Test _get_available_agents returns correct indices."""
    agent_availability = {
        "claude": AgentAvailabilityInfo(
            agent="claude",
            available=False,
            unavailable_until=None,
            reason="rate_limited",
        ),
        "gemini": AgentAvailabilityInfo(
            agent="gemini",
            available=True,
            unavailable_until=None,
            reason=None,
        ),
        "codex": AgentAvailabilityInfo(
            agent="codex",
            available=True,
            unavailable_until=None,
            reason=None,
        ),
    }

    modal = StartSessionModal(
        computer="local",
        project_path="/home/user/project",
        api=mock_api,
        agent_availability=agent_availability,
    )

    available = modal._get_available_agents()
    assert available == [1, 2]  # gemini and codex


def test_modal_skips_unavailable_agents_in_navigation(mock_api):
    """Test modal navigation skips unavailable agents."""
    agent_availability = {
        "claude": AgentAvailabilityInfo(
            agent="claude",
            available=False,
            unavailable_until=None,
            reason="rate_limited",
        ),
        "gemini": AgentAvailabilityInfo(
            agent="gemini",
            available=True,
            unavailable_until=None,
            reason=None,
        ),
        "codex": AgentAvailabilityInfo(
            agent="codex",
            available=True,
            unavailable_until=None,
            reason=None,
        ),
    }

    modal = StartSessionModal(
        computer="local",
        project_path="/home/user/project",
        api=mock_api,
        agent_availability=agent_availability,
    )

    # Should start at gemini (index 1)
    assert modal.selected_agent == 1

    # _get_available_agents should only return [1, 2]
    available = modal._get_available_agents()
    assert 0 not in available  # claude should be excluded


def test_modal_all_agents_unavailable(mock_api):
    """Test modal handles case when all agents are unavailable."""
    agent_availability = {
        "claude": AgentAvailabilityInfo(
            agent="claude",
            available=False,
            unavailable_until=None,
            reason="rate_limited",
        ),
        "gemini": AgentAvailabilityInfo(
            agent="gemini",
            available=False,
            unavailable_until=None,
            reason="rate_limited",
        ),
        "codex": AgentAvailabilityInfo(
            agent="codex",
            available=False,
            unavailable_until=None,
            reason="rate_limited",
        ),
    }

    modal = StartSessionModal(
        computer="local",
        project_path="/home/user/project",
        api=mock_api,
        agent_availability=agent_availability,
    )

    # Should still initialize (defaults to index 0 even if unavailable)
    assert modal.selected_agent == 0


def test_modal_empty_availability_dict(mock_api):
    """Test modal with empty agent_availability dict."""
    agent_availability = {}

    modal = StartSessionModal(
        computer="local",
        project_path="/home/user/project",
        api=mock_api,
        agent_availability=agent_availability,
    )

    # Unknown availability is treated as unavailable
    assert modal._is_agent_available("claude") is False
    assert modal._is_agent_available("gemini") is False
    assert modal._is_agent_available("codex") is False


def test_modal_init_values(mock_api):
    """Test modal initializes with correct values."""
    agent_availability = {
        "claude": AgentAvailabilityInfo(
            agent="claude",
            available=True,
            unavailable_until=None,
            reason=None,
        )
    }

    modal = StartSessionModal(
        computer="local",
        project_path="/home/user/project",
        api=mock_api,
        agent_availability=agent_availability,
    )

    assert modal.computer == "local"
    assert modal.project_path == "/home/user/project"
    assert modal.api == mock_api
    assert modal.prompt == ""
    assert modal.current_field == 0  # starts at agent field
