"""Unit tests for TUI agent status cycle logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.app import TelecApp
from teleclaude.cli.tui.messages import SettingsChanged
from tests.conftest import MockAPIClient


@pytest.fixture
def mock_status_bar():  # type: ignore[explicit-any, unused-ignore]
    """Create a mock StatusBar widget."""
    status_bar = MagicMock()
    status_bar._agent_availability = {}
    status_bar.refresh = MagicMock()
    return status_bar


@pytest.mark.unit
class TestAgentStatusCycle:
    """Verify agent status cycle logic in on_settings_changed handler."""

    @pytest.mark.asyncio
    async def test_available_to_degraded_cycle(self, mock_status_bar):  # type: ignore[explicit-any, unused-ignore]
        """Clicking an available agent pill should set it to degraded."""
        api = MockAPIClient()
        app = TelecApp(api)

        with patch.object(app, "query_one", return_value=mock_status_bar):
            # Setup current state: claude is available
            mock_status_bar._agent_availability = {
                "claude": AgentAvailabilityInfo(
                    agent="claude",
                    available=True,
                    status="available",
                    unavailable_until=None,
                    degraded_until=None,
                    reason=None,
                )
            }

            # Mock API call
            mock_set_agent_status = AsyncMock(
                return_value=AgentAvailabilityInfo(
                    agent="claude",
                    available=True,
                    status="degraded",
                    unavailable_until=None,
                    degraded_until="2026-02-11T12:00:00Z",
                    reason="degraded_manual",
                )
            )
            setattr(api, "set_agent_status", mock_set_agent_status)

            # Trigger cycle
            message = SettingsChanged(key="agent_status", value={"agent": "claude"})
            await app.on_settings_changed(message)

            # Verify API was called with degraded status
            mock_set_agent_status.assert_called_once_with("claude", "degraded", reason="manual", duration_minutes=60)
            # Verify local state was updated
            assert mock_status_bar._agent_availability["claude"].status == "degraded"
            # Verify UI was refreshed
            mock_status_bar.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_degraded_to_unavailable_cycle(self, mock_status_bar):  # type: ignore[explicit-any, unused-ignore]
        """Clicking a degraded agent pill should set it to unavailable."""
        api = MockAPIClient()
        app = TelecApp(api)

        with patch.object(app, "query_one", return_value=mock_status_bar):
            # Setup current state: gemini is degraded
            mock_status_bar._agent_availability = {
                "gemini": AgentAvailabilityInfo(
                    agent="gemini",
                    available=True,
                    status="degraded",
                    unavailable_until=None,
                    degraded_until="2026-02-11T12:00:00Z",
                    reason="degraded_manual",
                )
            }

            # Mock API call
            mock_set_agent_status = AsyncMock(
                return_value=AgentAvailabilityInfo(
                    agent="gemini",
                    available=False,
                    status="unavailable",
                    unavailable_until="2026-02-11T13:00:00Z",
                    degraded_until=None,
                    reason="manual",
                )
            )
            setattr(api, "set_agent_status", mock_set_agent_status)

            # Trigger cycle
            message = SettingsChanged(key="agent_status", value={"agent": "gemini"})
            await app.on_settings_changed(message)

            # Verify API was called with unavailable status
            mock_set_agent_status.assert_called_once_with("gemini", "unavailable", reason="manual", duration_minutes=60)
            # Verify local state was updated
            assert mock_status_bar._agent_availability["gemini"].status == "unavailable"
            # Verify UI was refreshed
            mock_status_bar.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_unavailable_to_available_cycle(self, mock_status_bar):  # type: ignore[explicit-any, unused-ignore]
        """Clicking an unavailable agent pill should set it to available."""
        api = MockAPIClient()
        app = TelecApp(api)

        with patch.object(app, "query_one", return_value=mock_status_bar):
            # Setup current state: codex is unavailable
            mock_status_bar._agent_availability = {
                "codex": AgentAvailabilityInfo(
                    agent="codex",
                    available=False,
                    status="unavailable",
                    unavailable_until="2026-02-11T13:00:00Z",
                    degraded_until=None,
                    reason="manual",
                )
            }

            # Mock API call
            mock_set_agent_status = AsyncMock(
                return_value=AgentAvailabilityInfo(
                    agent="codex",
                    available=True,
                    status="available",
                    unavailable_until=None,
                    degraded_until=None,
                    reason=None,
                )
            )
            setattr(api, "set_agent_status", mock_set_agent_status)

            # Trigger cycle
            message = SettingsChanged(key="agent_status", value={"agent": "codex"})
            await app.on_settings_changed(message)

            # Verify API was called with available status
            mock_set_agent_status.assert_called_once_with("codex", "available", reason="manual", duration_minutes=60)
            # Verify local state was updated
            assert mock_status_bar._agent_availability["codex"].status == "available"
            # Verify UI was refreshed
            mock_status_bar.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_current_info_defaults_to_degraded(self, mock_status_bar):  # type: ignore[explicit-any, unused-ignore]
        """Clicking an agent with no current info should default to degraded."""
        api = MockAPIClient()
        app = TelecApp(api)

        with patch.object(app, "query_one", return_value=mock_status_bar):
            # Setup: no current info for claude
            mock_status_bar._agent_availability = {}

            # Mock API call
            mock_set_agent_status = AsyncMock(
                return_value=AgentAvailabilityInfo(
                    agent="claude",
                    available=True,
                    status="degraded",
                    unavailable_until=None,
                    degraded_until="2026-02-11T12:00:00Z",
                    reason="degraded_manual",
                )
            )
            setattr(api, "set_agent_status", mock_set_agent_status)

            # Trigger cycle
            message = SettingsChanged(key="agent_status", value={"agent": "claude"})
            await app.on_settings_changed(message)

            # Verify API was called with degraded status (default when no current info)
            mock_set_agent_status.assert_called_once_with("claude", "degraded", reason="manual", duration_minutes=60)
            # Verify local state was updated
            assert mock_status_bar._agent_availability["claude"].status == "degraded"
            # Verify UI was refreshed
            mock_status_bar.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_api_error_shows_notification(self, mock_status_bar):  # type: ignore[explicit-any, unused-ignore]
        """API errors should trigger error notification."""
        api = MockAPIClient()
        app = TelecApp(api)

        with (
            patch.object(app, "query_one", return_value=mock_status_bar),
            patch.object(app, "notify") as mock_notify,
        ):
            # Setup current state
            mock_status_bar._agent_availability = {
                "claude": AgentAvailabilityInfo(
                    agent="claude",
                    available=True,
                    status="available",
                    unavailable_until=None,
                    degraded_until=None,
                    reason=None,
                )
            }

            # Mock API to raise exception
            mock_set_agent_status = AsyncMock(side_effect=Exception("Network timeout"))
            setattr(api, "set_agent_status", mock_set_agent_status)

            # Trigger cycle
            message = SettingsChanged(key="agent_status", value={"agent": "claude"})
            await app.on_settings_changed(message)

            # Verify error notification was shown
            mock_notify.assert_called_once()
            call_args = mock_notify.call_args
            assert "Failed to set agent status" in call_args[0][0]
            assert call_args[1]["severity"] == "error"
