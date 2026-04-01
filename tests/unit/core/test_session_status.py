"""Unit tests for teleclaude.core.session_status."""
# pylint: disable=missing-function-docstring,missing-class-docstring

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from teleclaude.core.session_status import compute_agent_status


class TestComputeAgentStatus:
    @pytest.mark.unit
    def test_unknown_when_no_activity(self):
        assert compute_agent_status(last_activity=None, last_input_at=None, last_agent_stop_at=None) == "unknown"

    @pytest.mark.unit
    def test_active_when_activity_exists_and_no_stop(self):
        activity = datetime(2025, 2, 1, 12, 0, 5, tzinfo=UTC)
        assert compute_agent_status(last_activity=activity, last_input_at=activity, last_agent_stop_at=None) == "active"

    @pytest.mark.unit
    def test_idle_when_stop_matches_activity(self):
        stop = datetime(2025, 2, 1, 12, 0, 5, tzinfo=UTC)
        input_at = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)
        assert compute_agent_status(last_activity=stop, last_input_at=input_at, last_agent_stop_at=stop) == "idle"

    @pytest.mark.unit
    def test_active_when_new_input_after_stop(self):
        """New input after stop means a new turn started — agent is active."""
        stop = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)
        input_at = datetime(2025, 2, 1, 12, 0, 5, tzinfo=UTC)
        activity = datetime(2025, 2, 1, 12, 0, 6, tzinfo=UTC)
        assert compute_agent_status(last_activity=activity, last_input_at=input_at, last_agent_stop_at=stop) == "active"

    @pytest.mark.unit
    def test_idle_when_poller_flushes_after_stop(self):
        """Poller activity after stop without new input — stop is authoritative."""
        input_at = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)
        stop = datetime(2025, 2, 1, 12, 0, 5, tzinfo=UTC)
        activity = datetime(2025, 2, 1, 12, 0, 6, tzinfo=UTC)  # poller flush after stop
        assert compute_agent_status(last_activity=activity, last_input_at=input_at, last_agent_stop_at=stop) == "idle"

    @pytest.mark.unit
    def test_idle_when_no_input_at_all(self):
        """Stop received but no input timestamp — still idle."""
        stop = datetime(2025, 2, 1, 12, 0, 5, tzinfo=UTC)
        activity = datetime(2025, 2, 1, 12, 0, 6, tzinfo=UTC)
        assert compute_agent_status(last_activity=activity, last_input_at=None, last_agent_stop_at=stop) == "idle"
