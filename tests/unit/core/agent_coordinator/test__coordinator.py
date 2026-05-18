"""Characterization tests for teleclaude.core.agent_coordinator._coordinator."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.agent_coordinator._coordinator import AgentCoordinator
from teleclaude.core.events import AgentHookEvents, TeleClaudeEvents
from teleclaude.core.models import Session
from teleclaude.core.origins import InputOrigin

ACTIVE_OUTPUT_STATUS = "active_output"
ACTIVE_STATUS = "active"
ACCEPTED_STATUS = "accepted"
AGENT_SESSION_STARTED_REASON = "agent_session_started"
AGENT_RESPONSE = "Agent response here."
BASH_TOOL_NAME = "Bash"
COMPLETED_STATUS = "completed"
FINAL_OUTPUT = "final output"
LINK_OUTPUT = "link output"
LAST_ACTIVITY_FIELD = "last_activity"
LAST_AGENT_STOP_AT_FIELD = "last_agent_stop_at"
LAST_INPUT_ORIGIN_FIELD = "last_input_origin"
LAST_MESSAGE_SENT_AT_FIELD = "last_message_sent_at"
LAST_MESSAGE_SENT_FIELD = "last_message_sent"
NATIVE_SESSION_ID_FIELD = "native_session_id"
PROJECT_PATH_FIELD = "project_path"
SCHEDULE_EVENT_TYPE_FIELD = "event_type"
SCHEDULE_SESSION_ID_FIELD = "session_id"
LAST_OUTPUT_AT_FIELD = "last_output_at"
LAST_OUTPUT_RAW_FIELD = "last_output_raw"
LAST_OUTPUT_SUMMARY_FIELD = "last_output_summary"
LAST_TOOL_DONE_AT_FIELD = "last_tool_done_at"
LAST_TOOL_USE_AT_FIELD = "last_tool_use_at"
LATE_CONTENT = "Late content."
NATIVE_SESSION_ID = "native-123"
PROMPT_TEXT = "fix the bug"
PROJECT_PATH = "/my/project"
RAW_AGENT_TEXT = "Raw agent text."
REPO_PATH = "/repo"
SESSION_ID = "sess-001"
SHORT_SUMMARY = "Short summary."
TOOL_PREVIEW = "$ ls"
TTS_SUMMARY = "The task is done."
TURN_ANCHOR_SHA = "abc123"
TURN_ANCHOR_SHA_FIELD = "turn_anchor_sha"


def _make_coordinator() -> AgentCoordinator:
    client = MagicMock()
    client.break_threaded_turn = AsyncMock()
    client.send_output_update = AsyncMock()
    tts_manager = MagicMock()
    return AgentCoordinator(
        client=client,
        tts_manager=tts_manager,
    )


class TestAgentCoordinatorInit:
    @pytest.mark.unit
    def test_initial_state_dicts_empty(self):
        coord = _make_coordinator()
        assert coord._last_emitted_status == {}

    @pytest.mark.unit
    def test_background_tasks_set_empty(self):
        coord = _make_coordinator()
        assert coord._background_tasks == set()

    @pytest.mark.unit
    def test_client_stored(self):
        client = MagicMock()
        coord = AgentCoordinator(
            client=client,
            tts_manager=MagicMock(),
        )
        assert coord.client is client


class TestEmitActivityEvent:
    @pytest.mark.unit
    def test_emits_to_event_bus(self):
        coord = _make_coordinator()
        with (
            patch("teleclaude.core.agent_coordinator._coordinator.serialize_activity_event") as mock_serial,
            patch("teleclaude.core.agent_coordinator._coordinator.event_bus") as mock_bus,
        ):
            mock_canonical = MagicMock()
            mock_canonical.canonical_type = "agent_output_stop"
            mock_canonical.message_intent = "ctrl_activity"
            mock_canonical.delivery_scope = "CTRL"
            mock_serial.return_value = mock_canonical
            coord._emit_activity_event(SESSION_ID, AgentHookEvents.AGENT_STOP)

        mock_bus.emit.assert_called_once()
        call_args = mock_bus.emit.call_args
        assert call_args[0][0] == TeleClaudeEvents.AGENT_ACTIVITY

    @pytest.mark.unit
    def test_emitted_payload_has_session_id(self):
        coord = _make_coordinator()
        with (
            patch("teleclaude.core.agent_coordinator._coordinator.serialize_activity_event") as mock_serial,
            patch("teleclaude.core.agent_coordinator._coordinator.event_bus") as mock_bus,
        ):
            mock_canonical = MagicMock()
            mock_canonical.canonical_type = "user_prompt_submit"
            mock_canonical.message_intent = "ctrl_activity"
            mock_canonical.delivery_scope = "CTRL"
            mock_serial.return_value = mock_canonical
            coord._emit_activity_event(SESSION_ID, AgentHookEvents.USER_PROMPT_SUBMIT)

        emitted_payload = mock_bus.emit.call_args[0][1]
        assert emitted_payload.session_id == SESSION_ID

    @pytest.mark.unit
    def test_serializer_failure_does_not_raise(self):
        coord = _make_coordinator()
        with patch(
            "teleclaude.core.agent_coordinator._coordinator.serialize_activity_event",
            side_effect=RuntimeError("serializer down"),
        ):
            # Should not raise — failures are logged and swallowed
            coord._emit_activity_event(SESSION_ID, AgentHookEvents.TOOL_USE)

    @pytest.mark.unit
    def test_tool_name_forwarded_to_payload(self):
        coord = _make_coordinator()
        with (
            patch("teleclaude.core.agent_coordinator._coordinator.serialize_activity_event") as mock_serial,
            patch("teleclaude.core.agent_coordinator._coordinator.event_bus") as mock_bus,
        ):
            mock_canonical = MagicMock()
            mock_canonical.canonical_type = "agent_output_update"
            mock_canonical.message_intent = "ctrl_activity"
            mock_canonical.delivery_scope = "CTRL"
            mock_serial.return_value = mock_canonical
            coord._emit_activity_event(SESSION_ID, AgentHookEvents.TOOL_USE, tool_name=BASH_TOOL_NAME)

        emitted_payload = mock_bus.emit.call_args[0][1]
        assert emitted_payload.tool_name == BASH_TOOL_NAME


class TestEmitStatusEvent:
    @pytest.mark.unit
    def test_emits_session_status_to_event_bus(self):
        coord = _make_coordinator()
        with (
            patch("teleclaude.core.agent_coordinator._coordinator.serialize_status_event") as mock_serial,
            patch("teleclaude.core.agent_coordinator._coordinator.event_bus") as mock_bus,
        ):
            mock_canonical = MagicMock()
            mock_canonical.message_intent = "ctrl_status"
            mock_canonical.delivery_scope = "CTRL"
            mock_serial.return_value = mock_canonical
            coord._emit_status_event(SESSION_ID, ACTIVE_STATUS, AGENT_SESSION_STARTED_REASON)

        mock_bus.emit.assert_called_once()
        call_args = mock_bus.emit.call_args
        assert call_args[0][0] == TeleClaudeEvents.SESSION_STATUS

    @pytest.mark.unit
    def test_tracks_last_emitted_status(self):
        coord = _make_coordinator()
        with (
            patch("teleclaude.core.agent_coordinator._coordinator.serialize_status_event") as mock_serial,
            patch("teleclaude.core.agent_coordinator._coordinator.event_bus"),
        ):
            mock_canonical = MagicMock()
            mock_canonical.message_intent = "ctrl_status"
            mock_canonical.delivery_scope = "CTRL"
            mock_serial.return_value = mock_canonical
            coord._emit_status_event(SESSION_ID, COMPLETED_STATUS, "agent_turn_complete")

        assert coord._last_emitted_status[SESSION_ID] == COMPLETED_STATUS

    @pytest.mark.unit
    def test_none_canonical_skips_event_emission(self):
        coord = _make_coordinator()
        with (
            patch(
                "teleclaude.core.agent_coordinator._coordinator.serialize_status_event",
                return_value=None,
            ),
            patch("teleclaude.core.agent_coordinator._coordinator.event_bus") as mock_bus,
        ):
            coord._emit_status_event(SESSION_ID, ACTIVE_STATUS, "some_reason")

        mock_bus.emit.assert_not_called()
        assert SESSION_ID not in coord._last_emitted_status

    @pytest.mark.unit
    def test_serializer_failure_does_not_raise(self):
        coord = _make_coordinator()
        with patch(
            "teleclaude.core.agent_coordinator._coordinator.serialize_status_event",
            side_effect=RuntimeError("status contract down"),
        ):
            # Should not raise — failures are logged and swallowed
            coord._emit_status_event(SESSION_ID, ACTIVE_STATUS, "some_reason")


class TestHandleEvent:
    @pytest.mark.unit
    async def test_dispatches_session_start(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.event_type = AgentHookEvents.AGENT_SESSION_START
        coord.handle_session_start = AsyncMock()
        await coord.handle_event(context)
        coord.handle_session_start.assert_called_once_with(context)

    @pytest.mark.unit
    async def test_dispatches_agent_stop(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.event_type = AgentHookEvents.AGENT_STOP
        coord.handle_agent_stop = AsyncMock()
        await coord.handle_event(context)
        coord.handle_agent_stop.assert_called_once_with(context)

    @pytest.mark.unit
    async def test_dispatches_tool_use(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.event_type = AgentHookEvents.TOOL_USE
        coord.handle_tool_use = AsyncMock()
        await coord.handle_event(context)
        coord.handle_tool_use.assert_called_once_with(context)

    @pytest.mark.unit
    async def test_dispatches_user_prompt_submit(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.event_type = AgentHookEvents.USER_PROMPT_SUBMIT
        coord.handle_user_prompt_submit = AsyncMock()
        await coord.handle_event(context)
        coord.handle_user_prompt_submit.assert_called_once_with(context)

    @pytest.mark.unit
    async def test_unknown_event_type_dispatches_nothing(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.event_type = "unknown_event"
        coord.handle_session_start = AsyncMock()
        coord.handle_agent_stop = AsyncMock()
        await coord.handle_event(context)
        coord.handle_session_start.assert_not_called()
        coord.handle_agent_stop.assert_not_called()


def _make_session(**kwargs: object) -> Session:
    defaults: dict[str, object] = {  # guard: loose-dict - Session factory accepts varied field types
        "session_id": SESSION_ID,
        "computer_name": "local",
        "tmux_session_name": "test",
        "title": "Test Session",
    }
    defaults.update(kwargs)
    return Session(**defaults)


class TestHandleSessionStart:
    @pytest.mark.unit
    async def test_updates_db_with_native_session_id(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.session_id = NATIVE_SESSION_ID
        context.data.transcript_path = None
        context.data.raw = {}

        with patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            mock_db.update_session = AsyncMock()
            mock_db.get_voice = AsyncMock(return_value=None)
            coord._emit_status_event = MagicMock()
            coord._speak_session_start = AsyncMock()
            await coord.handle_session_start(context)

        call_kwargs = mock_db.update_session.call_args[1]
        assert call_kwargs[NATIVE_SESSION_ID_FIELD] == NATIVE_SESSION_ID

    @pytest.mark.unit
    async def test_emits_active_status_for_non_headless(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.session_id = "n-1"
        context.data.transcript_path = None
        context.data.raw = {}
        session = _make_session(lifecycle_status="active")

        with patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.get_voice = AsyncMock(return_value=None)
            coord._emit_status_event = MagicMock()
            coord._speak_session_start = AsyncMock()
            await coord.handle_session_start(context)

        coord._emit_status_event.assert_called_once_with(SESSION_ID, ACTIVE_STATUS, AGENT_SESSION_STARTED_REASON)

    @pytest.mark.unit
    async def test_skips_status_for_headless_session(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.session_id = "n-1"
        context.data.transcript_path = None
        context.data.raw = {}
        session = _make_session(lifecycle_status="headless")

        with patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.get_voice = AsyncMock(return_value=None)
            coord._emit_status_event = MagicMock()
            coord._speak_session_start = AsyncMock()
            await coord.handle_session_start(context)

        coord._emit_status_event.assert_not_called()

    @pytest.mark.unit
    async def test_sets_project_path_when_session_has_none(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.session_id = "n-1"
        context.data.transcript_path = None
        context.data.raw = {"cwd": PROJECT_PATH}
        session = _make_session(project_path=None)

        with patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.get_voice = AsyncMock(return_value=None)
            coord._emit_status_event = MagicMock()
            coord._speak_session_start = AsyncMock()
            await coord.handle_session_start(context)

        call_kwargs = mock_db.update_session.call_args[1]
        assert call_kwargs[PROJECT_PATH_FIELD] == PROJECT_PATH

    @pytest.mark.unit
    async def test_schedules_speak_on_session_start(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.session_id = "n-1"
        context.data.transcript_path = None
        context.data.raw = {}

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.schedule_slow_work") as mock_schedule,
        ):
            mock_db.get_session = AsyncMock(return_value=None)
            mock_db.update_session = AsyncMock()
            mock_db.get_voice = AsyncMock(return_value=None)
            coord._emit_status_event = MagicMock()
            coord._speak_session_start = AsyncMock()
            await coord.handle_session_start(context)

        mock_schedule.assert_called_once()
        schedule_kwargs = mock_schedule.call_args.kwargs
        assert schedule_kwargs[SCHEDULE_SESSION_ID_FIELD] == SESSION_ID
        assert schedule_kwargs[SCHEDULE_EVENT_TYPE_FIELD] == AgentHookEvents.AGENT_SESSION_START


class TestHandleUserPromptSubmit:
    async def _run_normal_prompt(
        self,
    ) -> tuple[AgentCoordinator, MagicMock]:
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.prompt = PROMPT_TEXT
        context.data.raw = {}
        session = _make_session(lifecycle_status="active", active_agent="claude")

        def _close_coro(coro: object, label: str) -> None:
            if hasattr(coro, "close"):
                coro.close()  # pyright: ignore[reportAttributeAccessIssue]

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator._is_checkpoint_prompt", return_value=False),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.polling_coordinator.schedule_session_projection",
                AsyncMock(),
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_last_activity = AsyncMock()
            mock_db.set_notification_flag = AsyncMock()
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._queue_background_task = MagicMock(side_effect=_close_coro)
            await coord.handle_user_prompt_submit(context)

        return coord, context

    @pytest.mark.unit
    async def test_no_session_returns_early(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.prompt = "hello"
        context.data.raw = {}

        with patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await coord.handle_user_prompt_submit(context)

        mock_db.update_session.assert_not_called()

    @pytest.mark.unit
    async def test_empty_prompt_returns_early(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.prompt = "   "
        context.data.raw = {}
        session = _make_session()

        with patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            await coord.handle_user_prompt_submit(context)

        mock_db.update_session.assert_not_called()

    @pytest.mark.unit
    async def test_checkpoint_prompt_returns_early(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.prompt = "some checkpoint"
        context.data.raw = {}
        session = _make_session()

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator._is_checkpoint_prompt", return_value=True),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            await coord.handle_user_prompt_submit(context)

        mock_db.update_session.assert_not_called()

    @pytest.mark.unit
    async def test_snapshots_head_sha_when_project_is_git_repo(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.prompt = PROMPT_TEXT
        context.data.raw = {}
        session = _make_session(lifecycle_status="active", project_path=REPO_PATH)

        def _close_coro(coro: object, label: str) -> None:
            if hasattr(coro, "close"):
                coro.close()  # pyright: ignore[reportAttributeAccessIssue]

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator._is_checkpoint_prompt", return_value=False),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.polling_coordinator.schedule_session_projection",
                AsyncMock(),
            ),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.read_head_sha",
                return_value=TURN_ANCHOR_SHA,
            ) as read_head_mock,
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_last_activity = AsyncMock()
            mock_db.set_notification_flag = AsyncMock()
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._queue_background_task = MagicMock(side_effect=_close_coro)
            await coord.handle_user_prompt_submit(context)

        read_head_mock.assert_called_once_with(REPO_PATH)
        anchor_calls = [c for c in mock_db.update_session.call_args_list if TURN_ANCHOR_SHA_FIELD in c.kwargs]
        assert len(anchor_calls) == 1
        assert anchor_calls[0].kwargs[TURN_ANCHOR_SHA_FIELD] == TURN_ANCHOR_SHA

    @pytest.mark.unit
    async def test_skips_head_snapshot_when_project_path_missing(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.prompt = PROMPT_TEXT
        context.data.raw = {}
        session = _make_session(lifecycle_status="active", project_path=None)

        def _close_coro(coro: object, label: str) -> None:
            if hasattr(coro, "close"):
                coro.close()  # pyright: ignore[reportAttributeAccessIssue]

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator._is_checkpoint_prompt", return_value=False),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.polling_coordinator.schedule_session_projection",
                AsyncMock(),
            ),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.read_head_sha",
            ) as read_head_mock,
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_last_activity = AsyncMock()
            mock_db.set_notification_flag = AsyncMock()
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._queue_background_task = MagicMock(side_effect=_close_coro)
            await coord.handle_user_prompt_submit(context)

        read_head_mock.assert_not_called()
        anchor_calls = [c for c in mock_db.update_session.call_args_list if TURN_ANCHOR_SHA_FIELD in c.kwargs]
        assert len(anchor_calls) == 1
        assert anchor_calls[0].kwargs[TURN_ANCHOR_SHA_FIELD] is None

    @pytest.mark.unit
    async def test_normal_prompt_emits_activity_event(self):
        coord, _ = await self._run_normal_prompt()
        coord._emit_activity_event.assert_called_with(SESSION_ID, AgentHookEvents.USER_PROMPT_SUBMIT)

    @pytest.mark.unit
    async def test_normal_prompt_emits_accepted_status_for_non_headless(self):
        coord, _ = await self._run_normal_prompt()
        called_statuses = [c[0][1] for c in coord._emit_status_event.call_args_list]
        assert ACCEPTED_STATUS in called_statuses

    @pytest.mark.unit
    async def test_terminal_prompt_overwrites_stale_ui_origin_and_signals_projection(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.prompt = PROMPT_TEXT
        context.data.raw = {}
        projected_at = datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC)
        session = _make_session(
            lifecycle_status="active",
            active_agent="claude",
            last_input_origin=InputOrigin.DISCORD.value,
            last_message_sent="old prompt",
            last_message_sent_at=projected_at,
            last_projected_at=projected_at,
        )

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator._is_checkpoint_prompt", return_value=False),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.polling_coordinator.schedule_session_projection",
                AsyncMock(),
            ) as schedule_projection,
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_last_activity = AsyncMock()
            mock_db.set_notification_flag = AsyncMock()
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            await coord.handle_user_prompt_submit(context)

        terminal_writes = [
            call.kwargs for call in mock_db.update_session.await_args_list if LAST_INPUT_ORIGIN_FIELD in call.kwargs
        ]
        assert len(terminal_writes) == 1
        assert terminal_writes[0][LAST_INPUT_ORIGIN_FIELD] == InputOrigin.TERMINAL.value
        assert terminal_writes[0][LAST_MESSAGE_SENT_FIELD] == PROMPT_TEXT
        assert LAST_MESSAGE_SENT_AT_FIELD in terminal_writes[0]
        schedule_projection.assert_awaited_once_with(SESSION_ID, coord.client)

    @pytest.mark.unit
    async def test_fresh_ui_origin_is_preserved_and_does_not_signal_projection(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.prompt = PROMPT_TEXT
        context.data.raw = {}
        projected_at = datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC)
        accepted_at = datetime(2026, 4, 7, 12, 0, 2, tzinfo=UTC)
        session = _make_session(
            lifecycle_status="active",
            active_agent="claude",
            last_input_origin=InputOrigin.DISCORD.value,
            last_message_sent=PROMPT_TEXT,
            last_message_sent_at=accepted_at,
            last_projected_at=projected_at,
        )

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator._is_checkpoint_prompt", return_value=False),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.polling_coordinator.schedule_session_projection",
                AsyncMock(),
            ) as schedule_projection,
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_last_activity = AsyncMock()
            mock_db.set_notification_flag = AsyncMock()
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            await coord.handle_user_prompt_submit(context)

        assert not any(LAST_INPUT_ORIGIN_FIELD in call.kwargs for call in mock_db.update_session.await_args_list)
        schedule_projection.assert_not_awaited()


class TestHandleAgentStop:
    """Fast-path assertions for handle_agent_stop. The slow chain
    (summary, title, TTS) is exercised in TestRunAgentStopSlowWork; here we
    only verify that the handler returns quickly after fast row mutations,
    activity/status emit, finalize, and slow-work scheduling."""

    @pytest.mark.unit
    async def test_schedules_slow_work_for_agent_stop(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.source_computer = None

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.schedule_slow_work") as mock_schedule,
        ):
            mock_db.update_session = AsyncMock()
            coord._prepare_agent_stop_output = AsyncMock(return_value=(None, None))
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._signal_headless_activity = AsyncMock()
            coord._finalize_agent_stop = AsyncMock()
            await coord.handle_agent_stop(context)

        mock_schedule.assert_called_once()
        schedule_kwargs = mock_schedule.call_args.kwargs
        assert schedule_kwargs[SCHEDULE_SESSION_ID_FIELD] == SESSION_ID
        assert schedule_kwargs[SCHEDULE_EVENT_TYPE_FIELD] == AgentHookEvents.AGENT_STOP

    @pytest.mark.unit
    async def test_emits_completed_status(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.source_computer = None

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.schedule_slow_work"),
        ):
            mock_db.update_session = AsyncMock()
            coord._prepare_agent_stop_output = AsyncMock(return_value=(None, None))
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._signal_headless_activity = AsyncMock()
            coord._finalize_agent_stop = AsyncMock()
            await coord.handle_agent_stop(context)

        called_statuses = [c[0][1] for c in coord._emit_status_event.call_args_list]
        assert COMPLETED_STATUS in called_statuses

    @pytest.mark.unit
    async def test_records_last_agent_stop_at_and_last_activity(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.source_computer = None

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.schedule_slow_work"),
        ):
            mock_db.update_session = AsyncMock()
            coord._prepare_agent_stop_output = AsyncMock(return_value=(None, None))
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._signal_headless_activity = AsyncMock()
            coord._finalize_agent_stop = AsyncMock()
            await coord.handle_agent_stop(context)

        update_calls = mock_db.update_session.call_args_list
        stop_updates = [call.kwargs for call in update_calls if LAST_AGENT_STOP_AT_FIELD in call.kwargs]
        assert stop_updates
        assert any(
            LAST_ACTIVITY_FIELD in kwargs and kwargs[LAST_ACTIVITY_FIELD] == kwargs[LAST_AGENT_STOP_AT_FIELD]
            for kwargs in stop_updates
        )

    @pytest.mark.unit
    async def test_emits_immediate_activity_without_summary(self):
        """Handler emits the AGENT_STOP activity event synchronously with
        ``summary=None``. The slow runner re-emits with the computed summary
        (see TestRunAgentStopSlowWork)."""
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.source_computer = None

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.schedule_slow_work"),
        ):
            mock_db.update_session = AsyncMock()
            coord._prepare_agent_stop_output = AsyncMock(return_value=(None, None))
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._signal_headless_activity = AsyncMock()
            coord._finalize_agent_stop = AsyncMock()
            await coord.handle_agent_stop(context)

        coord._emit_activity_event.assert_called_once_with(SESSION_ID, AgentHookEvents.AGENT_STOP, summary=None)

    @pytest.mark.unit
    async def test_does_not_clear_last_tool_done_at(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.source_computer = None

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.schedule_slow_work"),
        ):
            mock_db.update_session = AsyncMock()
            coord._prepare_agent_stop_output = AsyncMock(return_value=(None, None))
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._signal_headless_activity = AsyncMock()
            coord._finalize_agent_stop = AsyncMock()
            await coord.handle_agent_stop(context)

        # last_tool_done_at is no longer cleared at agent_stop — the cadence
        # loop owns the cursor and nulling it caused duplicate turn breaks.
        update_calls = mock_db.update_session.call_args_list
        assert not any(
            LAST_TOOL_DONE_AT_FIELD in c.kwargs and c.kwargs[LAST_TOOL_DONE_AT_FIELD] is None for c in update_calls
        )

    @pytest.mark.unit
    async def test_finalizes_stop_with_prepared_link_output(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.source_computer = None

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.schedule_slow_work"),
        ):
            mock_db.update_session = AsyncMock()
            coord._prepare_agent_stop_output = AsyncMock(return_value=("raw text", FINAL_OUTPUT))
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._signal_headless_activity = AsyncMock()
            coord._finalize_agent_stop = AsyncMock()
            await coord.handle_agent_stop(context)

        coord._finalize_agent_stop.assert_awaited_once()
        finalize_args = coord._finalize_agent_stop.await_args.args
        assert finalize_args[2] == FINAL_OUTPUT


class TestFinalizeAgentStop:
    @pytest.mark.unit
    async def test_schedules_debounced_delivery_unconditionally(self):
        coord = _make_coordinator()
        coord._notify_session_listener = AsyncMock()
        coord._forward_stop_to_initiator = AsyncMock()

        payload = MagicMock()
        payload.raw = {}

        with (
            patch(
                "teleclaude.core.agent_coordinator._coordinator.schedule_debounced_delivery",
            ) as mock_schedule,
            patch("teleclaude.core.agent_coordinator._coordinator.get_command_service") as mock_cs,
        ):
            mock_cs.return_value = MagicMock()
            await coord._finalize_agent_stop(SESSION_ID, payload, LINK_OUTPUT, None)

        mock_schedule.assert_called_once_with(
            SESSION_ID,
            client=coord.client,
            command_service=mock_cs.return_value,
            source_computer=None,
        )
        coord._notify_session_listener.assert_awaited_once()
        coord._forward_stop_to_initiator.assert_awaited_once_with(SESSION_ID, LINK_OUTPUT)


class TestHandleToolUse:
    @pytest.mark.unit
    async def test_emits_activity_event_with_tool_name(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.raw = {}
        session = _make_session(last_tool_use_at=None)

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.extract_tool_name", return_value=BASH_TOOL_NAME),
            patch("teleclaude.core.agent_coordinator._coordinator.build_tool_preview", return_value=TOOL_PREVIEW),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._clear_tool_use_skip = MagicMock()  # pyright: ignore[reportAttributeAccessIssue]
            await coord.handle_tool_use(context)

        coord._emit_activity_event.assert_called_once_with(
            SESSION_ID, AgentHookEvents.TOOL_USE, BASH_TOOL_NAME, tool_preview=TOOL_PREVIEW
        )

    @pytest.mark.unit
    async def test_emits_active_output_status(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.raw = {}
        session = _make_session(last_tool_use_at=None)

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.extract_tool_name", return_value=None),
            patch("teleclaude.core.agent_coordinator._coordinator.build_tool_preview", return_value=None),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._clear_tool_use_skip = MagicMock()  # pyright: ignore[reportAttributeAccessIssue]
            await coord.handle_tool_use(context)

        called_statuses = [c[0][1] for c in coord._emit_status_event.call_args_list]
        assert ACTIVE_OUTPUT_STATUS in called_statuses

    @pytest.mark.unit
    async def test_first_tool_use_records_in_db(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.raw = {}
        session = _make_session(last_tool_use_at=None)

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.extract_tool_name", return_value=None),
            patch("teleclaude.core.agent_coordinator._coordinator.build_tool_preview", return_value=None),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_last_activity = AsyncMock()
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            await coord.handle_tool_use(context)

        mock_db.update_session.assert_called_once()
        call_kwargs = mock_db.update_session.call_args[1]
        assert LAST_TOOL_USE_AT_FIELD in call_kwargs

    @pytest.mark.unit
    async def test_subsequent_tool_use_skips_db_write(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = SESSION_ID
        context.data.raw = {}
        session = _make_session(last_tool_use_at=datetime.now(UTC))

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.extract_tool_name", return_value=None),
            patch("teleclaude.core.agent_coordinator._coordinator.build_tool_preview", return_value=None),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_last_activity = AsyncMock()
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            await coord.handle_tool_use(context)

        mock_db.update_session.assert_not_called()


class TestQueueBackgroundTask:
    """Tests use mock tasks to avoid asyncio.sleep(0) interactions with pytest-timeout/xdist."""

    def _run_done_callback(self, coord: AgentCoordinator, task: MagicMock) -> None:
        """Simulate task completion by invoking the registered done callback."""
        callback = task.add_done_callback.call_args[0][0]
        coord._background_tasks.add(task)
        callback(task)

    @pytest.mark.unit
    def test_task_added_to_background_tasks(self):
        coord = _make_coordinator()
        mock_task = MagicMock()
        with patch("teleclaude.core.agent_coordinator._coordinator.asyncio") as mock_asyncio:
            mock_asyncio.create_task.return_value = mock_task
            coord._queue_background_task(MagicMock(), "test-label")
        coord._background_tasks.add(mock_task)
        assert mock_task in coord._background_tasks

    @pytest.mark.unit
    def test_done_callback_removes_task(self):
        coord = _make_coordinator()
        mock_task = MagicMock()
        mock_task.result.return_value = None
        with patch("teleclaude.core.agent_coordinator._coordinator.asyncio") as mock_asyncio:
            mock_asyncio.create_task.return_value = mock_task
            coord._queue_background_task(MagicMock(), "test-label")
        self._run_done_callback(coord, mock_task)
        assert mock_task not in coord._background_tasks

    @pytest.mark.unit
    def test_task_exception_logs_error(self):
        coord = _make_coordinator()
        mock_task = MagicMock()
        mock_task.result.side_effect = RuntimeError("task failed")
        with (
            patch("teleclaude.core.agent_coordinator._coordinator.asyncio") as mock_asyncio,
            patch("teleclaude.core.agent_coordinator._coordinator.logger") as mock_logger,
        ):
            mock_asyncio.create_task.return_value = mock_task
            mock_asyncio.CancelledError = asyncio.CancelledError
            coord._queue_background_task(MagicMock(), "other-label")
            self._run_done_callback(coord, mock_task)
        mock_logger.error.assert_called_once()

    @pytest.mark.unit
    def test_title_task_failure_emits_error_event(self):
        coord = _make_coordinator()
        mock_task = MagicMock()
        mock_task.result.side_effect = RuntimeError("title update failed")
        with (
            patch("teleclaude.core.agent_coordinator._coordinator.asyncio") as mock_asyncio,
            patch("teleclaude.core.agent_coordinator._coordinator.logger"),
            patch("teleclaude.core.agent_coordinator._coordinator.event_bus") as mock_bus,
        ):
            mock_asyncio.create_task.return_value = mock_task
            mock_asyncio.CancelledError = asyncio.CancelledError
            coord._queue_background_task(MagicMock(), "title-summary:sess-001")
            self._run_done_callback(coord, mock_task)
        mock_bus.emit.assert_called_once()

    @pytest.mark.unit
    def test_cancelled_task_does_not_log_error(self):
        coord = _make_coordinator()
        mock_task = MagicMock()
        mock_task.result.side_effect = asyncio.CancelledError()
        with (
            patch("teleclaude.core.agent_coordinator._coordinator.asyncio") as mock_asyncio,
            patch("teleclaude.core.agent_coordinator._coordinator.logger") as mock_logger,
        ):
            mock_asyncio.create_task.return_value = mock_task
            mock_asyncio.CancelledError = asyncio.CancelledError
            coord._queue_background_task(MagicMock(), "test-label")
            self._run_done_callback(coord, mock_task)
        mock_logger.error.assert_not_called()


class TestPrepareAgentStopOutput:
    """Fast extraction + link-output normalization. No LLM, no TTS, no DB."""

    @pytest.mark.unit
    async def test_no_raw_output_returns_none_link(self):
        coord = _make_coordinator()
        payload = MagicMock()
        payload.raw = {}
        payload.prompt = None
        coord._extract_agent_output = AsyncMock(return_value=None)

        raw_output, link_output = await coord._prepare_agent_stop_output("sess-001", payload)

        assert raw_output is None
        assert link_output is None

    @pytest.mark.unit
    async def test_raw_output_becomes_link_output(self):
        coord = _make_coordinator()
        payload = MagicMock()
        payload.raw = {}
        payload.prompt = None
        coord._extract_agent_output = AsyncMock(return_value=AGENT_RESPONSE)

        with patch("teleclaude.core.agent_coordinator._coordinator.config") as mock_config:
            mock_config.terminal.strip_ansi = False
            raw_output, link_output = await coord._prepare_agent_stop_output(SESSION_ID, payload)

        assert raw_output == AGENT_RESPONSE
        assert link_output == AGENT_RESPONSE

    @pytest.mark.unit
    async def test_checkpoint_prompt_nullifies_link_output(self):
        coord = _make_coordinator()
        payload = MagicMock()
        payload.raw = {}
        payload.prompt = "checkpoint-prompt"
        coord._extract_agent_output = AsyncMock(return_value="some output")

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.config") as mock_config,
            patch("teleclaude.core.agent_coordinator._coordinator._is_checkpoint_prompt", return_value=True),
        ):
            mock_config.terminal.strip_ansi = False
            _, link_output = await coord._prepare_agent_stop_output(SESSION_ID, payload)

        assert link_output is None


class TestRunAgentStopSlowWork:
    """Slow runner: summarize, persist, re-emit activity, TTS, title."""

    @pytest.mark.unit
    async def test_no_raw_output_skips_db_write_and_tts(self):
        coord = _make_coordinator()
        coord._summarize_output = AsyncMock()
        coord._speak_agent_stop_summary = AsyncMock()
        coord._emit_activity_event = MagicMock()
        # session.native_log_file is None → wait_for_transcript_ready returns
        # True immediately (semantic absence). re-extract returns None too.
        coord._prepare_agent_stop_output = AsyncMock(return_value=(None, None))
        payload = MagicMock()

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._coordinator.generate_session_title_from_transcript",
                AsyncMock(),
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=_make_session())
            mock_db.update_session = AsyncMock()
            await coord._run_agent_stop_slow_work(SESSION_ID, payload, None)

        mock_db.update_session.assert_not_called()
        coord._speak_agent_stop_summary.assert_not_called()
        coord._emit_activity_event.assert_not_called()

    @pytest.mark.unit
    async def test_raw_output_persists_summary_and_emits_activity_and_speaks(self):
        coord = _make_coordinator()
        coord._summarize_output = AsyncMock(return_value=SHORT_SUMMARY)
        coord._speak_agent_stop_summary = AsyncMock()
        coord._emit_activity_event = MagicMock()
        payload = MagicMock()

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._coordinator.generate_session_title_from_transcript",
                AsyncMock(),
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=_make_session())
            mock_db.update_session = AsyncMock()
            await coord._run_agent_stop_slow_work(SESSION_ID, payload, AGENT_RESPONSE)

        update_kwargs = mock_db.update_session.call_args.kwargs
        assert update_kwargs[LAST_OUTPUT_RAW_FIELD] == AGENT_RESPONSE
        assert update_kwargs[LAST_OUTPUT_SUMMARY_FIELD] == SHORT_SUMMARY
        coord._emit_activity_event.assert_called_once_with(
            SESSION_ID, AgentHookEvents.AGENT_STOP, summary=SHORT_SUMMARY
        )
        coord._speak_agent_stop_summary.assert_called_once_with(SESSION_ID, SHORT_SUMMARY)

    @pytest.mark.unit
    async def test_generates_title_from_session(self):
        coord = _make_coordinator()
        coord._summarize_output = AsyncMock(return_value=None)
        coord._speak_agent_stop_summary = AsyncMock()
        coord._emit_activity_event = MagicMock()
        coord._prepare_agent_stop_output = AsyncMock(return_value=(None, None))
        session = _make_session()
        payload = MagicMock()

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._coordinator.generate_session_title_from_transcript",
                AsyncMock(),
            ) as mock_generate_title,
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            await coord._run_agent_stop_slow_work(SESSION_ID, payload, None)

        mock_generate_title.assert_awaited_once()
        assert mock_generate_title.await_args.args[0].session_id == SESSION_ID

    @pytest.mark.unit
    async def test_initial_none_with_expected_transcript_waits_then_reextracts(self):
        """When the synchronous extract missed and the file is expected to
        exist, the slow runner waits for the transcript and re-extracts."""
        coord = _make_coordinator()
        coord._summarize_output = AsyncMock(return_value=SHORT_SUMMARY)
        coord._speak_agent_stop_summary = AsyncMock()
        coord._emit_activity_event = MagicMock()
        coord._prepare_agent_stop_output = AsyncMock(return_value=(LATE_CONTENT, LATE_CONTENT))
        session = _make_session(native_log_file="/tmp/late.jsonl", active_agent="claude")
        payload = MagicMock()

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._coordinator.wait_for_transcript_ready",
                new=AsyncMock(return_value=True),
            ) as mock_wait,
            patch(
                "teleclaude.core.agent_coordinator._coordinator.generate_session_title_from_transcript",
                AsyncMock(),
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            await coord._run_agent_stop_slow_work(SESSION_ID, payload, None)

        mock_wait.assert_awaited_once()
        coord._prepare_agent_stop_output.assert_awaited_once()
        update_kwargs = mock_db.update_session.call_args.kwargs
        assert update_kwargs[LAST_OUTPUT_RAW_FIELD] == LATE_CONTENT
        assert update_kwargs[LAST_OUTPUT_SUMMARY_FIELD] == SHORT_SUMMARY
        coord._emit_activity_event.assert_called_once_with(
            SESSION_ID, AgentHookEvents.AGENT_STOP, summary=SHORT_SUMMARY
        )

    @pytest.mark.unit
    async def test_raw_output_persists_even_when_summary_fails(self):
        """Regression: summarize returning None must not drop the raw
        output. Raw is the fallback display path when LLM summary is
        unavailable; persisting only on summary success silently regresses
        output visibility for any turn where the summarizer errors or
        produces empty text."""
        coord = _make_coordinator()
        coord._summarize_output = AsyncMock(return_value=None)
        coord._speak_agent_stop_summary = AsyncMock()
        coord._emit_activity_event = MagicMock()
        payload = MagicMock()

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._coordinator.generate_session_title_from_transcript",
                AsyncMock(),
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=_make_session())
            mock_db.update_session = AsyncMock()
            await coord._run_agent_stop_slow_work(SESSION_ID, payload, RAW_AGENT_TEXT)

        update_kwargs = mock_db.update_session.call_args.kwargs
        assert update_kwargs[LAST_OUTPUT_RAW_FIELD] == RAW_AGENT_TEXT
        assert LAST_OUTPUT_AT_FIELD in update_kwargs
        # last_output_summary must be written as None when summarize fails,
        # so any stale summary from a prior turn is cleared instead of
        # being left to bleed into this turn's display.
        assert LAST_OUTPUT_SUMMARY_FIELD in update_kwargs
        assert update_kwargs[LAST_OUTPUT_SUMMARY_FIELD] is None
        # Summary-gated lanes do not fire when there is no summary.
        coord._emit_activity_event.assert_not_called()
        coord._speak_agent_stop_summary.assert_not_called()


class TestSpeakAgentStopSummary:
    @pytest.mark.unit
    async def test_empty_summary_skips_tts(self):
        coord = _make_coordinator()
        coord.tts_manager.speak = AsyncMock()
        await coord._speak_agent_stop_summary("sess-001", None)
        coord.tts_manager.speak.assert_not_called()

    @pytest.mark.unit
    async def test_valid_summary_calls_tts(self):
        coord = _make_coordinator()
        coord.tts_manager.speak = AsyncMock()
        await coord._speak_agent_stop_summary(SESSION_ID, TTS_SUMMARY)
        coord.tts_manager.speak.assert_called_once_with(TTS_SUMMARY, session_id=SESSION_ID)

    @pytest.mark.unit
    async def test_tts_exception_does_not_propagate(self):
        coord = _make_coordinator()
        coord.tts_manager.speak = AsyncMock(side_effect=RuntimeError("tts error"))
        # Should not raise — exception swallowing contract
        await coord._speak_agent_stop_summary("sess-001", "Some summary.")
