"""Tests for teleclaude.core.polling_coordinator helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

import teleclaude.core.polling_coordinator as pc
import teleclaude.core.session_title as session_title
from teleclaude.core.models import Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.polling_coordinator import (
    _build_transcript_output_update,
    _cleanup_codex_input_state,
    _percentile,
    _try_bind_codex_transcript,
    project_session_from_transcript,
)

LAST_PROJECTED_OUTPUT_DIGEST_FIELD = "last_projected_output_digest"
LAST_TOOL_DONE_AT_FIELD = "last_tool_done_at"
NATIVE_LOG_FILE = "/tmp/transcript.jsonl"
ASSISTANT_TEXT = "assistant text"
INTEGRATOR_COMMAND = "/next-integrate"
RENDERED_TEXT = "rendered"
LATEST_REQUEST = "latest request"
TITLE_ASSISTANT_MESSAGE = "first part\n\nsecond part"
SESSION_INTEGRATOR_ID = "sess-integrator-1"
SESSION_ORIGIN_HINT_1 = "sess-origin-hint-1"
SESSION_ORIGIN_HINT_2 = "sess-origin-hint-2"
SESSION_USER_1 = "sess-user-1"
SHIP_IT = "ship it"
SINCE_TIMESTAMP_FIELD = "since_timestamp"
STABLE_TITLE = "Stable title"
TERMINAL_ORIGIN = InputOrigin.TERMINAL.value
TMUX_DIRECT_INPUT = "tmux direct input"
TYPED_IN_BROWSER = "typed in browser"
TYPED_IN_DISCORD = "typed in discord"
USER_ROLE = "user"
ASSISTANT_ROLE = "assistant"


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
def _reset_codex_sets() -> Generator[None, None, None]:
    pc._codex_transcript_bind_attempted.clear()
    yield
    pc._codex_transcript_bind_attempted.clear()


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
                return_value=NATIVE_LOG_FILE,
            ),
            patch("teleclaude.core.polling_coordinator.db", mock_db),
        ):
            result = await _try_bind_codex_transcript(session)
        assert result is True
        mock_db.update_session.assert_called_once_with(session.session_id, native_log_file=NATIVE_LOG_FILE)
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
    def test_discards_from_transcript_bind_set(self):
        sid = "sess-cleanup-1"
        pc._codex_transcript_bind_attempted.add(sid)
        _cleanup_codex_input_state(sid)
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
                return_value=(RENDERED_TEXT, last_ts),
            ) as render,
        ):
            update = _build_transcript_output_update(session)

        assert update == (RENDERED_TEXT, last_ts, True)
        # Cursor must be the turn start anchor, not a per-tool cursor, so each
        # render produces the full cumulative view of the current turn.
        assert render.call_args.kwargs[SINCE_TIMESTAMP_FIELD] == turn_start_ts

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
        assert render.call_args_list[0].kwargs[SINCE_TIMESTAMP_FIELD] == turn_start_ts
        assert render.call_args_list[1].kwargs[SINCE_TIMESTAMP_FIELD] == turn_start_ts


class TestProjectSessionFromTranscript:
    @pytest.mark.unit
    async def test_projects_transcript_user_message_to_discord_reflection(self):
        session = Session(
            session_id=SESSION_USER_1,
            computer_name="local",
            tmux_session_name="tmux-user-1",
            title="Untitled",
            active_agent="codex",
            native_log_file=NATIVE_LOG_FILE,
            last_input_origin=TERMINAL_ORIGIN,
        )
        transcript_ts = datetime(2026, 4, 7, 12, 0, 1, tzinfo=UTC)
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=(SHIP_IT, transcript_ts),
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

        adapter_client.broadcast_user_input.assert_awaited_once_with(session, SHIP_IT, TERMINAL_ORIGIN)
        mock_db.update_session.assert_awaited_once_with(
            SESSION_USER_1,
            last_message_sent=SHIP_IT,
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
                return_value=(TMUX_DIRECT_INPUT, transcript_ts),
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

        adapter_client.broadcast_user_input.assert_awaited_once_with(session, TMUX_DIRECT_INPUT, TERMINAL_ORIGIN)

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
            session_id=SESSION_INTEGRATOR_ID,
            computer_name="local",
            tmux_session_name="tmux-integrator-1",
            title="/next-integrate",
            active_agent="claude",
            native_log_file=NATIVE_LOG_FILE,
            last_input_origin=TERMINAL_ORIGIN,
            system_role="integrator",
        )
        transcript_ts = datetime(2026, 4, 7, 12, 0, 1, tzinfo=UTC)
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=(INTEGRATOR_COMMAND, transcript_ts),
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

        adapter_client.broadcast_user_input.assert_awaited_once_with(session, INTEGRATOR_COMMAND, TERMINAL_ORIGIN)
        mock_db.update_session.assert_awaited_once_with(
            SESSION_INTEGRATOR_ID,
            last_message_sent=INTEGRATOR_COMMAND,
            last_message_sent_at=transcript_ts,
            last_projected_at=transcript_ts,
        )

    @pytest.mark.unit
    async def test_fresh_non_discord_origin_reflects_without_resetting_origin(self):
        session = Session(
            session_id=SESSION_ORIGIN_HINT_1,
            computer_name="local",
            tmux_session_name="tmux-origin-hint-1",
            title="Untitled",
            active_agent="codex",
            native_log_file=NATIVE_LOG_FILE,
            last_input_origin=InputOrigin.WEB.value,
            last_message_sent=TYPED_IN_BROWSER,
            last_message_sent_at=datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC),
        )
        transcript_ts = datetime(2026, 4, 7, 12, 0, 1, tzinfo=UTC)
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=(TYPED_IN_BROWSER, transcript_ts),
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

        adapter_client.broadcast_user_input.assert_awaited_once_with(session, TYPED_IN_BROWSER, InputOrigin.WEB.value)
        mock_db.update_session.assert_awaited_once_with(
            SESSION_ORIGIN_HINT_1,
            last_message_sent=TYPED_IN_BROWSER,
            last_message_sent_at=transcript_ts,
            last_projected_at=transcript_ts,
        )
        assert result.last_input_origin == InputOrigin.WEB.value

    @pytest.mark.unit
    async def test_fresh_discord_origin_is_skipped_without_resetting_origin(self):
        session = Session(
            session_id=SESSION_ORIGIN_HINT_2,
            computer_name="local",
            tmux_session_name="tmux-origin-hint-2",
            title="Untitled",
            active_agent="codex",
            native_log_file=NATIVE_LOG_FILE,
            last_input_origin=InputOrigin.DISCORD.value,
            last_message_sent=TYPED_IN_DISCORD,
            last_message_sent_at=datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC),
        )
        transcript_ts = datetime(2026, 4, 7, 12, 0, 1, tzinfo=UTC)
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=(TYPED_IN_DISCORD, transcript_ts),
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
        mock_db.update_session.assert_awaited_once_with(
            SESSION_ORIGIN_HINT_2,
            last_message_sent=TYPED_IN_DISCORD,
            last_message_sent_at=transcript_ts,
            last_projected_at=transcript_ts,
        )
        assert result.last_input_origin == InputOrigin.DISCORD.value

    @pytest.mark.unit
    async def test_non_terminal_origin_without_stored_preview_defers_projection(self):
        session = Session(
            session_id="sess-origin-missing-preview",
            computer_name="local",
            tmux_session_name="tmux-origin-missing-preview",
            title="Untitled",
            active_agent="codex",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin=InputOrigin.DISCORD.value,
            last_message_sent=None,
            last_message_sent_at=datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC),
        )
        transcript_ts = datetime(2026, 4, 7, 12, 0, 1, tzinfo=UTC)
        delivery_ts = datetime(2026, 4, 7, 12, 0, 2, tzinfo=UTC)
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=("unrelated transcript text", transcript_ts),
            ),
            patch(
                "teleclaude.core.polling_coordinator._build_transcript_output_update",
                return_value=(ASSISTANT_TEXT, delivery_ts, False),
            ),
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=session)
            result = await project_session_from_transcript(session, adapter_client)

        adapter_client.broadcast_user_input.assert_not_awaited()
        adapter_client.send_output_update.assert_not_awaited()
        mock_db.update_session.assert_not_awaited()
        assert result is session

    @pytest.mark.unit
    async def test_stale_non_terminal_origin_defers_user_and_output_projection(self):
        projected_ts = datetime(2026, 4, 7, 12, 0, 1, tzinfo=UTC)
        transcript_ts = datetime(2026, 4, 7, 12, 0, 5, tzinfo=UTC)
        session = Session(
            session_id="sess-origin-stale",
            computer_name="local",
            tmux_session_name="tmux-origin-stale",
            title="Untitled",
            active_agent="codex",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin="discord",
            last_message_sent="typed in terminal",
            last_message_sent_at=projected_ts,
            last_projected_at=projected_ts,
        )
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=("typed in terminal", transcript_ts),
            ),
            patch(
                "teleclaude.core.polling_coordinator._build_transcript_output_update",
                return_value=("assistant text", transcript_ts, False),
            ) as build_output,
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=session)
            result = await project_session_from_transcript(session, adapter_client)

        adapter_client.broadcast_user_input.assert_not_awaited()
        adapter_client.send_output_update.assert_not_awaited()
        build_output.assert_not_called()
        mock_db.update_session.assert_not_awaited()
        assert result is session

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
            last_message_sent="new input",
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
            assert LAST_TOOL_DONE_AT_FIELD not in call.kwargs
        assert any(LAST_PROJECTED_OUTPUT_DIGEST_FIELD in call.kwargs for call in mock_db.update_session.await_args_list)
        adapter_client.send_output_update.assert_awaited_once_with(
            session,
            ASSISTANT_TEXT,
            1.0,
            2.0,
            multi_message=False,
            delivery_ts=delivery_ts,
        )

    @pytest.mark.unit
    async def test_projection_skips_output_when_projected_digest_matches(self):
        session = Session(
            session_id="sess-output-dedupe-1",
            computer_name="local",
            tmux_session_name="tmux-output-dedupe-1",
            title="Title",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin="telegram",
        )
        delivery_ts = datetime(2026, 4, 7, 12, 3, 0, tzinfo=UTC)
        digest = pc._output_projection_digest("assistant text", delivery_ts, False)
        refreshed = Session.from_dict(session.to_dict() | {"last_projected_output_digest": digest})
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
            mock_db.get_session = AsyncMock(return_value=refreshed)
            first = await project_session_from_transcript(session, adapter_client, started_at=1.0, last_changed_at=2.0)
            await project_session_from_transcript(first, adapter_client, started_at=1.0, last_changed_at=2.0)

        adapter_client.send_output_update.assert_awaited_once()
        assert mock_db.update_session.await_count == 1

    @pytest.mark.unit
    async def test_projection_sends_same_text_again_when_delivery_cursor_changes(self):
        old_ts = datetime(2026, 4, 7, 12, 3, 0, tzinfo=UTC)
        new_ts = datetime(2026, 4, 7, 12, 4, 0, tzinfo=UTC)
        session = Session(
            session_id="sess-output-new-cursor",
            computer_name="local",
            tmux_session_name="tmux-output-new-cursor",
            title="Title",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
            last_input_origin="telegram",
            last_projected_output_digest=pc._output_projection_digest("assistant text", old_ts, False),
        )
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.polling_coordinator.extract_last_user_message_with_timestamp",
                return_value=None,
            ),
            patch(
                "teleclaude.core.polling_coordinator._build_transcript_output_update",
                return_value=("assistant text", new_ts, False),
            ),
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=session)
            await project_session_from_transcript(session, adapter_client, started_at=1.0, last_changed_at=2.0)

        adapter_client.send_output_update.assert_awaited_once()

    @pytest.mark.unit
    async def test_generate_session_title_preserves_slash_prefixed_titles(self):
        session = Session(
            session_id="sess-title-slash-1",
            computer_name="local",
            tmux_session_name="tmux-title-slash-1",
            title="/next-review-build",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
        )
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.session_title.collect_transcript_messages",
                return_value=[("user", "hello"), ("assistant", "world")],
            ),
            patch(
                "teleclaude.core.session_title.generate_session_title",
                AsyncMock(return_value="Overwritten title"),
            ) as mock_generate,
            patch("teleclaude.core.session_title.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            result = await session_title.generate_session_title_from_transcript(session, adapter_client)

        mock_generate.assert_not_awaited()
        mock_db.update_session.assert_not_awaited()
        adapter_client.update_channel_title.assert_not_awaited()
        assert result is session

    @pytest.mark.unit
    async def test_generate_session_title_uses_last_completed_turn_only(self):
        session = Session(
            session_id="sess-title-2",
            computer_name="local",
            tmux_session_name="tmux-title-2",
            title="Current title",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
        )
        adapter_client = AsyncMock()
        title = "New title"
        with (
            patch(
                "teleclaude.core.session_title.extract_last_user_message_with_timestamp",
                return_value=("latest request", datetime(2026, 4, 18, 0, 0, 0, tzinfo=UTC)),
            ),
            patch(
                "teleclaude.core.session_title.collect_transcript_messages",
                return_value=[
                    ("user", "old request"),
                    ("assistant", "old answer"),
                    ("user", "latest request"),
                    ("assistant", "first part"),
                    ("assistant", "second part"),
                ],
            ),
            patch(
                "teleclaude.core.session_title.generate_session_title",
                AsyncMock(return_value=title),
            ) as mock_generate,
            patch("teleclaude.core.session_title.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            result = await session_title.generate_session_title_from_transcript(session, adapter_client)

        expected_title_messages = [(USER_ROLE, LATEST_REQUEST), (ASSISTANT_ROLE, TITLE_ASSISTANT_MESSAGE)]
        mock_generate.assert_awaited_once_with(expected_title_messages)
        mock_db.update_session.assert_awaited_once_with(session.session_id, title=title)
        adapter_client.update_channel_title.assert_awaited_once_with(session)
        assert result.title == title

    @pytest.mark.unit
    async def test_generate_session_title_runs_once_per_user_turn(self):
        session = Session(
            session_id="sess-title-turn-once",
            computer_name="local",
            tmux_session_name="tmux-title-turn-once",
            title="Current title",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
        )
        adapter_client = AsyncMock()

        with (
            patch(
                "teleclaude.core.session_title.extract_last_user_message_with_timestamp",
                return_value=("same request", datetime(2026, 4, 18, 0, 1, 0, tzinfo=UTC)),
            ),
            patch(
                "teleclaude.core.session_title.collect_transcript_messages",
                side_effect=[
                    [("user", "same request"), ("assistant", "first answer")],
                    [("user", "same request"), ("assistant", "first answer"), ("assistant", "later answer")],
                ],
            ),
            patch(
                "teleclaude.core.session_title.generate_session_title",
                AsyncMock(return_value=STABLE_TITLE),
            ) as mock_generate,
            patch("teleclaude.core.session_title.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            await session_title.generate_session_title_from_transcript(session, adapter_client)
            await session_title.generate_session_title_from_transcript(session, adapter_client)

        mock_generate.assert_awaited_once()
        mock_db.update_session.assert_awaited_once_with(session.session_id, title=STABLE_TITLE)
        adapter_client.update_channel_title.assert_awaited_once_with(session)

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
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=session)
            result = await project_session_from_transcript(session, adapter_client)

        adapter_client.send_output_update.assert_not_awaited()
        mock_db.update_session.assert_not_awaited()
        assert result is session

    @pytest.mark.unit
    async def test_generate_session_title_updates_passed_session(self):
        session = Session(
            session_id="sess-title-finalize-1",
            computer_name="local",
            tmux_session_name="tmux-title-finalize-1",
            title="Current title",
            active_agent="claude",
            native_log_file="/tmp/transcript.jsonl",
        )
        adapter_client = AsyncMock()
        title = "Generated title"

        with (
            patch(
                "teleclaude.core.session_title.extract_last_user_message_with_timestamp",
                return_value=("request", datetime(2026, 4, 18, 0, 2, 0, tzinfo=UTC)),
            ),
            patch(
                "teleclaude.core.session_title.collect_transcript_messages",
                return_value=[("user", "request"), ("assistant", "answer")],
            ),
            patch(
                "teleclaude.core.session_title.generate_session_title",
                AsyncMock(return_value=title),
            ),
            patch("teleclaude.core.session_title.db") as mock_db,
        ):
            mock_db.update_session = AsyncMock()
            result = await session_title.generate_session_title_from_transcript(session, adapter_client)

        mock_db.update_session.assert_awaited_once_with(session.session_id, title=title)
        adapter_client.update_channel_title.assert_awaited_once_with(session)
        assert result.title == title
        assert result is session


class TestScheduleHeadlessProjection:
    @pytest.fixture(autouse=True)
    def _reset_projection_state(self) -> Generator[None]:
        pc._active_headless_projections.clear()
        pc._pending_headless_projections.clear()
        yield
        pc._active_headless_projections.clear()
        pc._pending_headless_projections.clear()

    @pytest.mark.unit
    async def test_signal_during_projection_triggers_one_rerun(self) -> None:
        """A signal that lands while a projection is in flight must cause exactly
        one re-run. This guarantees a title update emitted concurrently with
        post-stop output projection is not dropped.
        """
        session = _make_session(session_id="sess-headless-coalesce")
        session.lifecycle_status = "headless"

        first_started = asyncio.Event()
        release_first = asyncio.Event()
        adapter_client = AsyncMock()
        call_count = {"value": 0}

        async def fake_project(*_args: object, **_kwargs: object) -> Session:
            call_count["value"] += 1
            if call_count["value"] == 1:
                first_started.set()
                await release_first.wait()
            return session

        with (
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
            patch(
                "teleclaude.core.polling_coordinator.project_session_from_transcript",
                AsyncMock(side_effect=fake_project),
            ) as project,
        ):
            mock_db.get_session = AsyncMock(return_value=session)

            assert await pc.schedule_headless_projection(session.session_id, adapter_client) is True
            await first_started.wait()

            # Signal lands while the first projection pass is still running.
            assert await pc.schedule_headless_projection(session.session_id, adapter_client) is False
            assert session.session_id in pc._pending_headless_projections

            release_first.set()

            # Wait for the inflight task to finish (it should re-run once).
            for _ in range(50):
                if call_count["value"] >= 2 and session.session_id not in pc._active_headless_projections:
                    break
                await asyncio.sleep(0.01)

        assert project.await_count == 2
        assert session.session_id not in pc._active_headless_projections
        assert session.session_id not in pc._pending_headless_projections

    @pytest.mark.unit
    async def test_signal_with_no_active_projection_runs_once(self) -> None:
        session = _make_session(session_id="sess-headless-single")
        session.lifecycle_status = "headless"
        adapter_client = AsyncMock()

        with (
            patch("teleclaude.core.polling_coordinator.db") as mock_db,
            patch(
                "teleclaude.core.polling_coordinator.project_session_from_transcript",
                AsyncMock(return_value=session),
            ) as project,
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            assert await pc.schedule_headless_projection(session.session_id, adapter_client) is True

            for _ in range(50):
                if session.session_id not in pc._active_headless_projections:
                    break
                await asyncio.sleep(0.01)

        assert project.await_count == 1
