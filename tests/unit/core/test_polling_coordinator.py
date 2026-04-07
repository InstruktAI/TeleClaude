"""Tests for teleclaude.core.polling_coordinator helpers."""
# pylint: disable=protected-access  # tests access module-private state sets intentionally

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

import teleclaude.core.polling_coordinator as pc
from teleclaude.core.models import Session
from teleclaude.core.polling_coordinator import (
    _build_transcript_output_update,
    _cleanup_codex_input_state,
    _emit_codex_session_start,
    _percentile,
    _try_bind_codex_transcript,
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


def _make_session(
    *,
    session_id: str = "sess-codex-1",
    computer_name: str = "local",
    tmux_session_name: str = "tmux-1",
    title: str = "Codex Test",
    active_agent: str | None = "codex",
    native_session_id: str | None = "native-sess-1",
    native_log_file: str | None = None,
) -> Session:
    return Session(
        session_id=session_id,
        computer_name=computer_name,
        tmux_session_name=tmux_session_name,
        title=title,
        active_agent=active_agent,
        native_session_id=native_session_id,
        native_log_file=native_log_file,
    )


@pytest.fixture(autouse=True)
def _reset_codex_sets() -> Generator[None, None, None]:  # pylint: disable=protected-access
    pc._codex_session_start_emitted.clear()
    pc._codex_transcript_bind_attempted.clear()
    yield
    pc._codex_session_start_emitted.clear()
    pc._codex_transcript_bind_attempted.clear()


class TestEmitCodexSessionStart:
    @pytest.mark.unit
    async def test_non_codex_session_is_noop(self):
        session = _make_session(active_agent="claude")
        emit = AsyncMock()
        with patch("teleclaude.core.polling_coordinator.discover_codex_transcript_path"):
            await _emit_codex_session_start(session, emit)
        emit.assert_not_called()
        assert session.session_id not in pc._codex_session_start_emitted

    @pytest.mark.unit
    async def test_first_call_emits_event_and_sets_guard(self):
        session = _make_session()
        emit = AsyncMock()
        with patch(
            "teleclaude.core.polling_coordinator.discover_codex_transcript_path",
            return_value="/tmp/transcript.jsonl",
        ):
            await _emit_codex_session_start(session, emit)
        emit.assert_called_once()
        assert session.session_id in pc._codex_session_start_emitted

    @pytest.mark.unit
    async def test_second_call_same_session_is_noop(self):
        session = _make_session()
        emit = AsyncMock()
        with patch(
            "teleclaude.core.polling_coordinator.discover_codex_transcript_path",
            return_value="/tmp/transcript.jsonl",
        ):
            await _emit_codex_session_start(session, emit)
            await _emit_codex_session_start(session, emit)
        emit.assert_called_once()

    @pytest.mark.unit
    async def test_guard_not_set_on_emission_failure(self):
        session = _make_session()
        emit = AsyncMock(side_effect=RuntimeError("emit failed"))
        with patch(
            "teleclaude.core.polling_coordinator.discover_codex_transcript_path",
            return_value="/tmp/transcript.jsonl",
        ):
            with pytest.raises(RuntimeError):
                await _emit_codex_session_start(session, emit)
        assert session.session_id not in pc._codex_session_start_emitted


class TestTryBindCodexTranscript:
    @pytest.mark.unit
    async def test_non_codex_session_returns_false(self):
        session = _make_session(active_agent="claude")
        result = await _try_bind_codex_transcript(session)
        assert result is False
        assert session.session_id not in pc._codex_transcript_bind_attempted

    @pytest.mark.unit
    async def test_transcript_found_calls_db_update_and_returns_true(self):
        session = _make_session()
        mock_db = AsyncMock()
        with (
            patch(
                "teleclaude.core.polling_coordinator.discover_codex_transcript_path",
                return_value="/tmp/transcript.jsonl",
            ),
            patch("teleclaude.core.polling_coordinator.db", mock_db),
        ):
            result = await _try_bind_codex_transcript(session)
        assert result is True
        mock_db.update_session.assert_called_once_with(session.session_id, native_log_file="/tmp/transcript.jsonl")
        assert session.session_id in pc._codex_transcript_bind_attempted

    @pytest.mark.unit
    async def test_transcript_not_found_returns_false_and_sets_guard(self):
        session = _make_session()
        with patch(
            "teleclaude.core.polling_coordinator.discover_codex_transcript_path",
            return_value=None,
        ):
            result = await _try_bind_codex_transcript(session)
        assert result is False
        assert session.session_id in pc._codex_transcript_bind_attempted

    @pytest.mark.unit
    async def test_already_attempted_returns_false(self):
        session = _make_session()
        pc._codex_transcript_bind_attempted.add(session.session_id)
        mock_discover = patch("teleclaude.core.polling_coordinator.discover_codex_transcript_path")
        with mock_discover as discover:
            result = await _try_bind_codex_transcript(session)
        discover.assert_not_called()
        assert result is False

    @pytest.mark.unit
    async def test_guard_not_set_when_db_update_fails(self):
        session = _make_session()
        mock_db = AsyncMock()
        mock_db.update_session.side_effect = RuntimeError("db error")
        with (
            patch(
                "teleclaude.core.polling_coordinator.discover_codex_transcript_path",
                return_value="/tmp/transcript.jsonl",
            ),
            patch("teleclaude.core.polling_coordinator.db", mock_db),
        ):
            with pytest.raises(RuntimeError):
                await _try_bind_codex_transcript(session)
        assert session.session_id not in pc._codex_transcript_bind_attempted


class TestCleanupCodexInputState:
    @pytest.mark.unit
    def test_discards_from_both_state_sets(self):
        sid = "sess-cleanup-1"
        pc._codex_session_start_emitted.add(sid)
        pc._codex_transcript_bind_attempted.add(sid)
        with patch("teleclaude.core.polling_coordinator.codex_prompt_submit"):
            _cleanup_codex_input_state(sid)
        assert sid not in pc._codex_session_start_emitted
        assert sid not in pc._codex_transcript_bind_attempted


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
