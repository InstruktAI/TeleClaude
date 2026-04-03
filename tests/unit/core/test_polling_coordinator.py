"""Tests for teleclaude.core.polling_coordinator helpers."""
# pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from teleclaude.core.models import Session
from teleclaude.core.polling_coordinator import _build_transcript_output_update, _percentile


class TestPercentile:
    @pytest.mark.unit
    def test_empty_values_returns_none(self):
        assert _percentile([], 0.5) is None

    @pytest.mark.unit
    def test_single_value_returns_it(self):
        assert _percentile([42.0], 0.5) == 42.0

    @pytest.mark.unit
    def test_median_of_sorted_list(self):
        result = _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5)
        assert result == 3.0

    @pytest.mark.unit
    def test_p95_approximation(self):
        values = list(range(1, 101))
        result = _percentile([float(v) for v in values], 0.95)
        assert result is not None
        assert result >= 90.0

    @pytest.mark.unit
    def test_p0_returns_minimum(self):
        result = _percentile([5.0, 3.0, 1.0, 4.0, 2.0], 0.0)
        assert result == 1.0


class TestBuildTranscriptOutputUpdate:
    @pytest.mark.unit
    def test_returns_rendered_message_and_delivery_timestamp(self):
        session = Session(
            session_id="sess-1",
            computer_name="local",
            tmux_session_name="tmux-sess-1",
            title="Demo",
            native_log_file="/tmp/transcript.jsonl",
            active_agent="claude",
            last_tool_done_at=datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC),
        )
        last_ts = datetime(2026, 4, 3, 12, 0, 5, tzinfo=UTC)

        with (
            patch(
                "teleclaude.core.polling_coordinator.get_assistant_messages_since",
                return_value=[{"role": "assistant"}],
            ),
            patch(
                "teleclaude.core.polling_coordinator.count_renderable_assistant_blocks",
                return_value=2,
            ),
            patch(
                "teleclaude.core.polling_coordinator.render_agent_output",
                return_value=("rendered", last_ts),
            ),
        ):
            update = _build_transcript_output_update(session)

        assert update == ("rendered", last_ts, True)
