"""Tests for teleclaude.core.polling_coordinator helpers."""
# pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.models import Session
from teleclaude.core.polling_coordinator import (
    CodexInputState,
    _build_transcript_output_update,
    _has_active_output_message,
    _maybe_emit_codex_session_start,
    _percentile,
)


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


class TestHasActiveOutputMessage:
    @pytest.mark.unit
    def test_returns_true_when_any_origin_section_has_output_message_id(self):
        session = Session(
            session_id="sess-1",
            computer_name="local",
            tmux_session_name="tmux-sess-1",
            title="Demo",
            origin_metadata={
                "discord": {"output_message_id": "msg-123"},
                "telegram": {},
            },
        )

        assert _has_active_output_message(session) is True

    @pytest.mark.unit
    def test_returns_false_when_no_origin_section_has_output_message_id(self):
        session = Session(
            session_id="sess-1",
            computer_name="local",
            tmux_session_name="tmux-sess-1",
            title="Demo",
            origin_metadata={
                "discord": {"output_message_id": None},
                "telegram": {},
            },
        )

        assert _has_active_output_message(session) is False


class TestMaybeEmitCodexSessionStart:
    @pytest.mark.unit
    async def test_emits_when_recent_unclaimed_candidate_resolves(self):
        session = Session(
            session_id="sess-1",
            computer_name="local",
            tmux_session_name="tmux-sess-1",
            title="Demo",
            active_agent="codex",
            created_at=datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC),
        )
        emit_agent_event = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator._codex_input_state",
                {"sess-1": CodexInputState(last_emitted_prompt="hello")},
            ),
            patch(
                "teleclaude.core.polling_coordinator.db.list_sessions",
                AsyncMock(return_value=[]),
            ),
            patch(
                "teleclaude.core.polling_coordinator.discover_recent_unclaimed_codex_transcript",
                return_value=type(
                    "Candidate",
                    (),
                    {
                        "native_session_id": "019d6240-e7ec-7c83-958e-a713996de5a6",
                        "transcript_path": "/tmp/rollout.jsonl",
                    },
                )(),
            ),
        ):
            result = await _maybe_emit_codex_session_start(session, emit_agent_event)

        assert result is True
        payload = emit_agent_event.await_args.args[0].data
        assert payload.session_id == "019d6240-e7ec-7c83-958e-a713996de5a6"
        assert payload.transcript_path == "/tmp/rollout.jsonl"

    @pytest.mark.unit
    async def test_uses_existing_native_session_id_to_fill_missing_path(self):
        session = Session(
            session_id="sess-1",
            computer_name="local",
            tmux_session_name="tmux-sess-1",
            title="Demo",
            active_agent="codex",
            created_at=datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC),
            native_session_id="019d6240-e7ec-7c83-958e-a713996de5a6",
        )
        emit_agent_event = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator._codex_input_state",
                {"sess-1": CodexInputState(last_emitted_prompt="hello")},
            ),
            patch(
                "teleclaude.core.polling_coordinator.discover_codex_transcript_path",
                return_value="/tmp/rollout.jsonl",
            ),
        ):
            result = await _maybe_emit_codex_session_start(session, emit_agent_event)

        assert result is True
        payload = emit_agent_event.await_args.args[0].data
        assert payload.session_id == "019d6240-e7ec-7c83-958e-a713996de5a6"
        assert payload.transcript_path == "/tmp/rollout.jsonl"

    @pytest.mark.unit
    async def test_skips_when_no_synthetic_submit_has_been_emitted(self):
        session = Session(
            session_id="sess-1",
            computer_name="local",
            tmux_session_name="tmux-sess-1",
            title="Demo",
            active_agent="codex",
            created_at=datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC),
        )
        emit_agent_event = AsyncMock()

        with patch("teleclaude.core.polling_coordinator._codex_input_state", {}):
            result = await _maybe_emit_codex_session_start(session, emit_agent_event)

        assert result is False
        emit_agent_event.assert_not_awaited()
