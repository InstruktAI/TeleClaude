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
    _assistant_projection_signature,
    _build_transcript_output_update,
    _cleanup_codex_input_state,
    _emit_codex_session_start,
    _percentile,
    _try_bind_codex_transcript,
    project_session_from_transcript,
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
    pc._title_projection_signatures.clear()
    yield
    pc._codex_session_start_emitted.clear()
    pc._codex_transcript_bind_attempted.clear()
    pc._title_projection_signatures.clear()


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
        )
        turn_start_ts = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)
        last_ts = datetime(2026, 4, 3, 12, 0, 5, tzinfo=UTC)

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_turn_boundary_timestamp",
                return_value=turn_start_ts,
            ),
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
            ) as render,
        ):
            update = _build_transcript_output_update(session)

        assert update == ("rendered", last_ts, True)
        # Cursor must be the turn start anchor, not a per-tool cursor, so each
        # render produces the full cumulative view of the current turn.
        assert render.call_args.kwargs["since_timestamp"] == turn_start_ts

    @pytest.mark.unit
    def test_renders_cumulative_turn_content_across_tool_calls(self):
        """Regression: tool calls must accumulate in the rendered view, not replace each other.

        Each render within a turn must re-read from the turn start anchor so
        Discord/Telegram edits produce an accumulating view. Using any cursor
        that advances within the turn (e.g. the last-tool-done timestamp)
        causes edits to wipe prior content.
        """
        session = Session(
            session_id="sess-accum",
            computer_name="local",
            tmux_session_name="tmux-accum",
            title="Demo",
            native_log_file="/tmp/transcript.jsonl",
            active_agent="claude",
        )
        turn_start_ts = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)
        tool1_ts = datetime(2026, 4, 3, 12, 0, 5, tzinfo=UTC)
        tool2_ts = datetime(2026, 4, 3, 12, 0, 10, tzinfo=UTC)

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_turn_boundary_timestamp",
                return_value=turn_start_ts,
            ),
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
                side_effect=[
                    ("text A\n\ntool 1", tool1_ts),
                    ("text A\n\ntool 1\n\ntool 2", tool2_ts),
                ],
            ) as render,
        ):
            first = _build_transcript_output_update(session)
            second = _build_transcript_output_update(session)

        assert first is not None
        assert second is not None
        # Both renders must use the same turn-start cursor, regardless of how
        # many tool calls completed between them.
        assert render.call_args_list[0].kwargs["since_timestamp"] == turn_start_ts
        assert render.call_args_list[1].kwargs["since_timestamp"] == turn_start_ts
        # The second render's content must be a superset (accumulating) of the first.
        assert first[0] in second[0]


class TestProjectSessionFromTranscript:
    @pytest.mark.unit
    async def test_projects_transcript_user_message_to_discord_reflection(self):
        session = Session(
            session_id="sess-user-1",
            computer_name="local",
            tmux_session_name="tmux-user-1",
            title="Untitled",
            active_agent="codex",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin="terminal",
        )
        transcript_ts = datetime(2026, 4, 7, 12, 0, 1, tzinfo=UTC)
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=("ship it", transcript_ts),
            ),
            patch(
                "teleclaude.core.polling_coordinator.extract_recent_transcript_turns",
                return_value=[],
            ),
            patch(
                "teleclaude.core.polling_coordinator._build_transcript_output_update",
                return_value=None,
            ),
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=session)
            await project_session_from_transcript(session, adapter_client)

        adapter_client.broadcast_user_input.assert_awaited_once_with(session, "ship it", "terminal")
        mock_db.update_session.assert_awaited_once_with(
            "sess-user-1",
            last_message_sent="ship it",
            last_input_origin="terminal",
            last_message_sent_at=transcript_ts,
            last_projected_at=transcript_ts,
        )

    @pytest.mark.unit
    async def test_non_projector_timestamp_does_not_suppress_transcript_truth(self):
        """Regression: non-projector writes to last_message_sent_at must not suppress projection.

        When deliver_inbound sets last_message_sent_at to a time newer than the transcript,
        the projector must still project the transcript truth because last_projected_at
        (the projection-owned watermark) has not advanced.
        """
        non_projector_ts = datetime(2026, 4, 7, 12, 0, 10, tzinfo=UTC)
        transcript_ts = datetime(2026, 4, 7, 12, 0, 5, tzinfo=UTC)
        session = Session(
            session_id="sess-regression-1",
            computer_name="local",
            tmux_session_name="tmux-regression-1",
            title="Untitled",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin="terminal",
            last_message_sent_at=non_projector_ts,
            last_projected_at=None,
        )
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=("tmux direct input", transcript_ts),
            ),
            patch(
                "teleclaude.core.polling_coordinator.extract_recent_transcript_turns",
                return_value=[],
            ),
            patch(
                "teleclaude.core.polling_coordinator._build_transcript_output_update",
                return_value=None,
            ),
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=session)
            await project_session_from_transcript(session, adapter_client)

        adapter_client.broadcast_user_input.assert_awaited_once_with(session, "tmux direct input", "terminal")

    @pytest.mark.unit
    async def test_same_projected_timestamp_does_not_re_reflect(self):
        """Once projected, the same transcript timestamp must not re-trigger."""
        long_text = "x" * 300
        transcript_ts = datetime(2026, 4, 7, 12, 0, 1, tzinfo=UTC)
        session = Session(
            session_id="sess-dedup-1",
            computer_name="local",
            tmux_session_name="tmux-dedup-1",
            title="Untitled",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin="terminal",
            last_projected_at=transcript_ts,
        )
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=(long_text, transcript_ts),
            ),
            patch(
                "teleclaude.core.polling_coordinator.extract_recent_transcript_turns",
                return_value=[],
            ),
            patch(
                "teleclaude.core.polling_coordinator._build_transcript_output_update",
                return_value=None,
            ),
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=session)
            await project_session_from_transcript(session, adapter_client)

        adapter_client.broadcast_user_input.assert_not_awaited()

    @pytest.mark.unit
    async def test_older_transcript_does_not_rewind_projection_watermark(self):
        projected_ts = datetime(2026, 4, 7, 12, 0, 5, tzinfo=UTC)
        transcript_ts = datetime(2026, 4, 7, 12, 0, 1, tzinfo=UTC)
        session = Session(
            session_id="sess-direct-1",
            computer_name="local",
            tmux_session_name="tmux-direct-1",
            title="Untitled",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin="terminal",
            last_projected_at=projected_ts,
        )
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=("older human prompt", transcript_ts),
            ),
            patch(
                "teleclaude.core.polling_coordinator.extract_recent_transcript_turns",
                return_value=[],
            ),
            patch(
                "teleclaude.core.polling_coordinator._build_transcript_output_update",
                return_value=None,
            ),
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=session)
            result = await project_session_from_transcript(session, adapter_client)

        adapter_client.broadcast_user_input.assert_not_awaited()
        mock_db.update_session.assert_not_awaited()
        assert result.last_projected_at == projected_ts

    @pytest.mark.unit
    async def test_system_role_session_reflects_prompt_to_discord_admin(self):
        session = Session(
            session_id="sess-integrator-1",
            computer_name="local",
            tmux_session_name="tmux-integrator-1",
            title="/next-integrate",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin="terminal",
            system_role="integrator",
        )
        transcript_ts = datetime(2026, 4, 7, 12, 0, 1, tzinfo=UTC)
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=("/next-integrate", transcript_ts),
            ),
            patch(
                "teleclaude.core.polling_coordinator.extract_recent_transcript_turns",
                return_value=[],
            ),
            patch(
                "teleclaude.core.polling_coordinator._build_transcript_output_update",
                return_value=None,
            ),
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=session)
            await project_session_from_transcript(session, adapter_client)

        adapter_client.broadcast_user_input.assert_awaited_once_with(session, "/next-integrate", "terminal")
        mock_db.update_session.assert_awaited_once_with(
            "sess-integrator-1",
            last_message_sent="/next-integrate",
            last_input_origin="terminal",
            last_message_sent_at=transcript_ts,
            last_projected_at=transcript_ts,
        )

    @pytest.mark.unit
    async def test_consumes_adapter_origin_hint_once_then_resets_to_terminal(self):
        session = Session(
            session_id="sess-origin-hint-1",
            computer_name="local",
            tmux_session_name="tmux-origin-hint-1",
            title="Untitled",
            active_agent="codex",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin="web",
        )
        transcript_ts = datetime(2026, 4, 7, 12, 0, 1, tzinfo=UTC)
        refreshed = Session.from_dict(session.to_dict() | {"last_input_origin": "terminal"})
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=("typed in browser", transcript_ts),
            ),
            patch(
                "teleclaude.core.polling_coordinator._build_transcript_output_update",
                return_value=None,
            ),
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=refreshed)
            result = await project_session_from_transcript(session, adapter_client)

        adapter_client.broadcast_user_input.assert_awaited_once_with(session, "typed in browser", "web")
        mock_db.update_session.assert_awaited_once_with(
            "sess-origin-hint-1",
            last_message_sent="typed in browser",
            last_input_origin="terminal",
            last_message_sent_at=transcript_ts,
            last_projected_at=transcript_ts,
        )
        assert result.last_input_origin == "terminal"

    @pytest.mark.unit
    async def test_discord_origin_is_suppressed_once_then_resets_to_terminal(self):
        session = Session(
            session_id="sess-origin-hint-2",
            computer_name="local",
            tmux_session_name="tmux-origin-hint-2",
            title="Untitled",
            active_agent="codex",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin="discord",
        )
        transcript_ts = datetime(2026, 4, 7, 12, 0, 1, tzinfo=UTC)
        refreshed = Session.from_dict(session.to_dict() | {"last_input_origin": "terminal"})
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=("typed in discord", transcript_ts),
            ),
            patch(
                "teleclaude.core.polling_coordinator._build_transcript_output_update",
                return_value=None,
            ),
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=refreshed)
            result = await project_session_from_transcript(session, adapter_client)

        adapter_client.broadcast_user_input.assert_not_awaited()
        mock_db.update_session.assert_awaited_once_with(
            "sess-origin-hint-2",
            last_message_sent="typed in discord",
            last_input_origin="terminal",
            last_message_sent_at=transcript_ts,
            last_projected_at=transcript_ts,
        )
        assert result.last_input_origin == "terminal"

    @pytest.mark.unit
    async def test_projection_dedupe_ignores_last_message_sent_at(self):
        """Canonical projection dedupe uses last_projected_at, not last_message_sent_at.

        last_message_sent_at may be set by any acceptance handler. The projector
        must not use it for dedupe decisions — only last_projected_at matters.
        """
        # last_message_sent_at is in the future (set by non-projector code),
        # but last_projected_at is None — projection must proceed.
        future_ts = datetime(2026, 4, 7, 12, 0, 30, tzinfo=UTC)
        transcript_ts = datetime(2026, 4, 7, 12, 0, 5, tzinfo=UTC)
        session = Session(
            session_id="sess-legacy-1",
            computer_name="local",
            tmux_session_name="tmux-legacy-1",
            title="Untitled",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin="terminal",
            last_message_sent="old text",
            last_message_sent_at=future_ts,
            last_projected_at=None,
        )
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=("new input", transcript_ts),
            ),
            patch(
                "teleclaude.core.polling_coordinator.extract_recent_transcript_turns",
                return_value=[],
            ),
            patch(
                "teleclaude.core.polling_coordinator._build_transcript_output_update",
                return_value=None,
            ),
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=session)
            await project_session_from_transcript(session, adapter_client)

        adapter_client.broadcast_user_input.assert_awaited_once()

    @pytest.mark.unit
    async def test_projects_transcript_output(self):
        session = Session(
            session_id="sess-title-1",
            computer_name="local",
            tmux_session_name="tmux-title-1",
            title="Old title",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin="telegram",
        )
        delivery_ts = datetime(2026, 4, 7, 12, 3, 0, tzinfo=UTC)
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=None,
            ),
            patch(
                "teleclaude.core.polling_coordinator._build_transcript_output_update",
                return_value=("assistant text", delivery_ts, False),
            ),
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=session)
            await project_session_from_transcript(session, adapter_client, started_at=1.0, last_changed_at=2.0)

        # The polling coordinator no longer writes a per-tool cursor to the DB;
        # the render pipeline derives its cursor fresh from the transcript's
        # turn start anchor on every projection so edits accumulate.
        for call in mock_db.update_session.await_args_list:
            assert "last_tool_done_at" not in call.kwargs
        adapter_client.send_output_update.assert_awaited_once_with(
            session,
            "assistant text",
            1.0,
            2.0,
            multi_message=False,
            delivery_ts=delivery_ts,
        )

    @pytest.mark.unit
    async def test_skips_output_delivery_when_transcript_render_digest_is_unchanged(self):
        session = Session(
            session_id="sess-output-dedupe-1",
            computer_name="local",
            tmux_session_name="tmux-output-dedupe-1",
            title="Old title",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin="telegram",
        )
        delivery_ts = datetime(2026, 4, 7, 12, 3, 0, tzinfo=UTC)
        session.last_projected_output_digest = _assistant_projection_signature("assistant text", delivery_ts)
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=None,
            ),
            patch(
                "teleclaude.core.polling_coordinator._build_transcript_output_update",
                return_value=("assistant text", delivery_ts, False),
            ),
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=session)
            result = await project_session_from_transcript(session, adapter_client, started_at=1.0, last_changed_at=2.0)

        adapter_client.send_output_update.assert_not_awaited()
        assert result is session

    @pytest.mark.unit
    async def test_refresh_session_title_preserves_slash_prefixed_titles(self):
        session = Session(
            session_id="sess-title-slash-1",
            computer_name="local",
            tmux_session_name="tmux-title-slash-1",
            title="/next-review-build",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
        )

        with (
            patch(
                "teleclaude.core.polling_coordinator.collect_transcript_messages",
                return_value=[("user", "hello"), ("assistant", "world")],
            ),
            patch(
                "teleclaude.core.polling_coordinator.generate_session_title",
                AsyncMock(return_value="Overwritten title"),
            ) as mock_generate,
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            result = await pc.refresh_session_title_from_transcript(session)

        mock_generate.assert_not_awaited()
        mock_db.update_session.assert_not_awaited()
        assert result is session

    @pytest.mark.unit
    async def test_refresh_session_title_uses_last_completed_turn_only(self):
        session = Session(
            session_id="sess-title-2",
            computer_name="local",
            tmux_session_name="tmux-title-2",
            title="Current title",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
        )
        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=("latest request", datetime(2026, 4, 18, 0, 0, 0, tzinfo=UTC)),
            ),
            patch(
                "teleclaude.core.polling_coordinator.collect_transcript_messages",
                return_value=[
                    ("user", "old request"),
                    ("assistant", "old answer"),
                    ("user", "latest request"),
                    ("assistant", "first part"),
                    ("assistant", "second part"),
                ],
            ),
            patch(
                "teleclaude.core.polling_coordinator.generate_session_title",
                AsyncMock(return_value="New title"),
            ) as mock_generate,
            patch("teleclaude.core.polling_coordinator.event_bus") as mock_bus,
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            result = await pc.refresh_session_title_from_transcript(session)

        mock_generate.assert_awaited_once_with([("user", "latest request"), ("assistant", "first part\n\nsecond part")])
        mock_db.update_session.assert_awaited_once_with(session.session_id, title="New title")
        mock_bus.emit.assert_called_once()
        emitted = mock_bus.emit.call_args.args[1]
        assert emitted.session_id == session.session_id
        assert emitted.title == "New title"
        assert result.title == "New title"

    @pytest.mark.unit
    async def test_refresh_session_title_runs_once_per_user_turn(self):
        session = Session(
            session_id="sess-title-turn-once",
            computer_name="local",
            tmux_session_name="tmux-title-turn-once",
            title="Current title",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
        )

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=("same request", datetime(2026, 4, 18, 0, 1, 0, tzinfo=UTC)),
            ),
            patch(
                "teleclaude.core.polling_coordinator.collect_transcript_messages",
                side_effect=[
                    [("user", "same request"), ("assistant", "first answer")],
                    [("user", "same request"), ("assistant", "first answer"), ("assistant", "later answer")],
                ],
            ),
            patch(
                "teleclaude.core.polling_coordinator.generate_session_title",
                AsyncMock(return_value="Stable title"),
            ) as mock_generate,
            patch("teleclaude.core.polling_coordinator.event_bus") as mock_bus,
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            await pc.refresh_session_title_from_transcript(session)
            await pc.refresh_session_title_from_transcript(session)

        mock_generate.assert_awaited_once()
        mock_db.update_session.assert_awaited_once_with(session.session_id, title="Stable title")
        mock_bus.emit.assert_called_once()

    @pytest.mark.unit
    async def test_project_session_does_not_update_title_during_live_output_projection(self):
        session = Session(
            session_id="sess-title-3",
            computer_name="local",
            tmux_session_name="tmux-title-3",
            title="Current title",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin="telegram",
        )
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=None,
            ),
            patch(
                "teleclaude.core.polling_coordinator._build_transcript_output_update",
                return_value=None,
            ),
            patch(
                "teleclaude.core.polling_coordinator.collect_transcript_messages",
                return_value=[("user", "hello"), ("assistant", "world")],
            ),
            patch(
                "teleclaude.core.polling_coordinator.generate_session_title",
                AsyncMock(return_value="New title"),
            ),
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=session)
            result = await project_session_from_transcript(session, adapter_client)

        adapter_client.send_output_update.assert_not_awaited()
        mock_db.update_session.assert_not_awaited()
        assert result is session

    @pytest.mark.unit
    async def test_finalize_session_title_on_agent_stop_fetches_session_and_refreshes(self):
        session = Session(
            session_id="sess-title-finalize-1",
            computer_name="local",
            tmux_session_name="tmux-title-finalize-1",
            title="Current title",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
        )

        with (
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
            patch(
                "teleclaude.core.polling_coordinator.refresh_session_title_from_transcript",
                AsyncMock(return_value=session),
            ) as mock_refresh,
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            result = await pc.finalize_session_title_on_agent_stop(session.session_id)

        mock_db.get_session.assert_awaited_once_with(session.session_id)
        mock_refresh.assert_awaited_once_with(session)
        assert result is session
