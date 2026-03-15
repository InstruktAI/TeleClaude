"""Characterization tests for teleclaude.core.agent_coordinator._coordinator."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.agent_coordinator._coordinator import AgentCoordinator
from teleclaude.core.events import AgentHookEvents, TeleClaudeEvents
from teleclaude.core.models import Session


def _make_coordinator() -> AgentCoordinator:
    client = MagicMock()
    tts_manager = MagicMock()
    headless_snapshot_service = MagicMock()
    return AgentCoordinator(
        client=client,
        tts_manager=tts_manager,
        headless_snapshot_service=headless_snapshot_service,
    )


class TestAgentCoordinatorInit:
    @pytest.mark.unit
    def test_initial_state_dicts_empty(self):
        coord = _make_coordinator()
        assert coord._incremental_noop_state == {}
        assert coord._tool_use_skip_state == {}
        assert coord._incremental_eval_state == {}
        assert coord._incremental_render_digests == {}
        assert coord._incremental_output_locks == {}
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
            headless_snapshot_service=MagicMock(),
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
            coord._emit_activity_event("sess-001", AgentHookEvents.AGENT_STOP)

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
            coord._emit_activity_event("sess-001", AgentHookEvents.USER_PROMPT_SUBMIT)

        emitted_payload = mock_bus.emit.call_args[0][1]
        assert emitted_payload.session_id == "sess-001"

    @pytest.mark.unit
    def test_serializer_failure_does_not_raise(self):
        coord = _make_coordinator()
        with patch(
            "teleclaude.core.agent_coordinator._coordinator.serialize_activity_event",
            side_effect=RuntimeError("serializer down"),
        ):
            # Should not raise — failures are logged and swallowed
            coord._emit_activity_event("sess-001", AgentHookEvents.TOOL_USE)

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
            coord._emit_activity_event("sess-001", AgentHookEvents.TOOL_USE, tool_name="Bash")

        emitted_payload = mock_bus.emit.call_args[0][1]
        assert emitted_payload.tool_name == "Bash"


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
            coord._emit_status_event("sess-001", "active", "agent_session_started")

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
            coord._emit_status_event("sess-001", "completed", "agent_turn_complete")

        assert coord._last_emitted_status["sess-001"] == "completed"

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
            coord._emit_status_event("sess-001", "active", "some_reason")

        mock_bus.emit.assert_not_called()
        assert "sess-001" not in coord._last_emitted_status

    @pytest.mark.unit
    def test_serializer_failure_does_not_raise(self):
        coord = _make_coordinator()
        with patch(
            "teleclaude.core.agent_coordinator._coordinator.serialize_status_event",
            side_effect=RuntimeError("status contract down"),
        ):
            # Should not raise — failures are logged and swallowed
            coord._emit_status_event("sess-001", "active", "some_reason")


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
    async def test_dispatches_tool_done(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.event_type = AgentHookEvents.TOOL_DONE
        coord.handle_tool_done = AsyncMock()
        await coord.handle_event(context)
        coord.handle_tool_done.assert_called_once_with(context)

    @pytest.mark.unit
    async def test_dispatches_user_prompt_submit(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.event_type = AgentHookEvents.USER_PROMPT_SUBMIT
        coord.handle_user_prompt_submit = AsyncMock()
        await coord.handle_event(context)
        coord.handle_user_prompt_submit.assert_called_once_with(context)

    @pytest.mark.unit
    async def test_dispatches_session_end(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.event_type = AgentHookEvents.AGENT_SESSION_END
        coord.handle_session_end = AsyncMock()
        await coord.handle_event(context)
        coord.handle_session_end.assert_called_once_with(context)

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


class TestHandleToolDone:
    @pytest.mark.unit
    async def test_emits_tool_done_activity(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        with (
            patch("teleclaude.core.agent_coordinator._coordinator.serialize_activity_event") as mock_serial,
            patch("teleclaude.core.agent_coordinator._coordinator.event_bus") as mock_bus,
        ):
            mock_canonical = MagicMock()
            mock_canonical.canonical_type = "agent_output_update"
            mock_canonical.message_intent = "ctrl_activity"
            mock_canonical.delivery_scope = "CTRL"
            mock_serial.return_value = mock_canonical
            await coord.handle_tool_done(context)

        mock_bus.emit.assert_called_once()
        emitted_payload = mock_bus.emit.call_args[0][1]
        assert emitted_payload.event_type == AgentHookEvents.TOOL_DONE


class TestHandleSessionEnd:
    @pytest.mark.unit
    async def test_completes_without_error(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data = MagicMock()
        # Should complete without raising — characterization of current behavior
        await coord.handle_session_end(context)


def _make_session(**kwargs: object) -> Session:
    defaults: dict[str, object] = {  # guard: loose-dict - Session factory accepts varied field types
        "session_id": "sess-001",
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
        context.session_id = "sess-001"
        context.data.session_id = "native-123"
        context.data.transcript_path = None
        context.data.raw = {}

        with patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            mock_db.update_session = AsyncMock()
            mock_db.get_voice = AsyncMock(return_value=None)
            coord._emit_status_event = MagicMock()
            coord._maybe_send_headless_snapshot = AsyncMock()
            coord._speak_session_start = AsyncMock()
            await coord.handle_session_start(context)

        call_kwargs = mock_db.update_session.call_args[1]
        assert call_kwargs["native_session_id"] == "native-123"

    @pytest.mark.unit
    async def test_emits_active_status_for_non_headless(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.session_id = "n-1"
        context.data.transcript_path = None
        context.data.raw = {}
        session = _make_session(lifecycle_status="active")

        with patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.get_voice = AsyncMock(return_value=None)
            coord._emit_status_event = MagicMock()
            coord._maybe_send_headless_snapshot = AsyncMock()
            coord._speak_session_start = AsyncMock()
            await coord.handle_session_start(context)

        coord._emit_status_event.assert_called_once_with("sess-001", "active", "agent_session_started")

    @pytest.mark.unit
    async def test_skips_status_for_headless_session(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.session_id = "n-1"
        context.data.transcript_path = None
        context.data.raw = {}
        session = _make_session(lifecycle_status="headless")

        with patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.get_voice = AsyncMock(return_value=None)
            coord._emit_status_event = MagicMock()
            coord._maybe_send_headless_snapshot = AsyncMock()
            coord._speak_session_start = AsyncMock()
            await coord.handle_session_start(context)

        coord._emit_status_event.assert_not_called()

    @pytest.mark.unit
    async def test_sets_project_path_when_session_has_none(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.session_id = "n-1"
        context.data.transcript_path = None
        context.data.raw = {"cwd": "/my/project"}
        session = _make_session(project_path=None)

        with patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.get_voice = AsyncMock(return_value=None)
            coord._emit_status_event = MagicMock()
            coord._maybe_send_headless_snapshot = AsyncMock()
            coord._speak_session_start = AsyncMock()
            await coord.handle_session_start(context)

        call_kwargs = mock_db.update_session.call_args[1]
        assert call_kwargs["project_path"] == "/my/project"

    @pytest.mark.unit
    async def test_calls_headless_snapshot_and_speak(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.session_id = "n-1"
        context.data.transcript_path = None
        context.data.raw = {}

        with patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            mock_db.update_session = AsyncMock()
            mock_db.get_voice = AsyncMock(return_value=None)
            coord._emit_status_event = MagicMock()
            coord._maybe_send_headless_snapshot = AsyncMock()
            coord._speak_session_start = AsyncMock()
            await coord.handle_session_start(context)

        coord._maybe_send_headless_snapshot.assert_called_once_with("sess-001")
        coord._speak_session_start.assert_called_once_with("sess-001")


class TestHandleUserPromptSubmit:
    @pytest.mark.unit
    async def test_no_session_returns_early(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
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
        context.session_id = "sess-001"
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
        context.session_id = "sess-001"
        context.data.prompt = "some checkpoint"
        context.data.raw = {}
        session = _make_session()

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator._is_checkpoint_prompt", return_value=True),
            patch(
                "teleclaude.core.agent_coordinator._coordinator._is_codex_synthetic_prompt_event", return_value=False
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            await coord.handle_user_prompt_submit(context)

        mock_db.update_session.assert_not_called()

    @pytest.mark.unit
    async def test_normal_prompt_emits_activity_event(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.prompt = "fix the bug"
        context.data.raw = {}
        session = _make_session(lifecycle_status="active", active_agent="claude")

        def _close_coro(coro: object, label: str) -> None:
            if hasattr(coro, "close"):
                coro.close()

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator._is_checkpoint_prompt", return_value=False),
            patch(
                "teleclaude.core.agent_coordinator._coordinator._is_codex_synthetic_prompt_event", return_value=False
            ),
            patch("teleclaude.core.agent_coordinator._coordinator._resolve_hook_actor_name", return_value="user"),
            patch("teleclaude.core.agent_coordinator._coordinator.is_threaded_output_enabled", return_value=False),
            patch("teleclaude.core.agent_coordinator._coordinator.TELECLAUDE_SYSTEM_PREFIX", "__TC__"),
            patch("teleclaude.core.agent_coordinator._coordinator.config") as mock_config,
        ):
            mock_config.computer.name = "local"
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.set_notification_flag = AsyncMock()
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._queue_background_task = MagicMock(side_effect=_close_coro)
            coord.client.broadcast_user_input = MagicMock(return_value=None)
            await coord.handle_user_prompt_submit(context)

        coord._emit_activity_event.assert_called_with("sess-001", AgentHookEvents.USER_PROMPT_SUBMIT)

    @pytest.mark.unit
    async def test_normal_prompt_emits_accepted_status_for_non_headless(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.prompt = "fix the bug"
        context.data.raw = {}
        session = _make_session(lifecycle_status="active", active_agent="claude")

        def _close_coro(coro: object, label: str) -> None:
            if hasattr(coro, "close"):
                coro.close()

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator._is_checkpoint_prompt", return_value=False),
            patch(
                "teleclaude.core.agent_coordinator._coordinator._is_codex_synthetic_prompt_event", return_value=False
            ),
            patch("teleclaude.core.agent_coordinator._coordinator._resolve_hook_actor_name", return_value="user"),
            patch("teleclaude.core.agent_coordinator._coordinator.is_threaded_output_enabled", return_value=False),
            patch("teleclaude.core.agent_coordinator._coordinator.TELECLAUDE_SYSTEM_PREFIX", "__TC__"),
            patch("teleclaude.core.agent_coordinator._coordinator.config") as mock_config,
        ):
            mock_config.computer.name = "local"
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.set_notification_flag = AsyncMock()
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._queue_background_task = MagicMock(side_effect=_close_coro)
            coord.client.broadcast_user_input = MagicMock(return_value=None)
            await coord.handle_user_prompt_submit(context)

        called_statuses = [c[0][1] for c in coord._emit_status_event.call_args_list]
        assert "accepted" in called_statuses


class TestHandleAgentStop:
    @pytest.mark.unit
    async def test_calls_record_input_and_output(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.source_computer = None

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.is_threaded_output_enabled", return_value=False),
        ):
            mock_db.get_session = AsyncMock(return_value=_make_session())
            mock_db.update_session = AsyncMock()
            coord._record_agent_stop_input = AsyncMock()
            coord._record_agent_stop_output = AsyncMock(return_value=(None, None))
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._maybe_send_incremental_output = AsyncMock(return_value=False)
            coord._finalize_agent_stop = AsyncMock()
            await coord.handle_agent_stop(context)

        coord._record_agent_stop_input.assert_called_once()
        coord._record_agent_stop_output.assert_called_once()

    @pytest.mark.unit
    async def test_emits_completed_status(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.source_computer = None

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.is_threaded_output_enabled", return_value=False),
        ):
            mock_db.get_session = AsyncMock(return_value=_make_session())
            mock_db.update_session = AsyncMock()
            coord._record_agent_stop_input = AsyncMock()
            coord._record_agent_stop_output = AsyncMock(return_value=(None, None))
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._maybe_send_incremental_output = AsyncMock(return_value=False)
            coord._finalize_agent_stop = AsyncMock()
            await coord.handle_agent_stop(context)

        called_statuses = [c[0][1] for c in coord._emit_status_event.call_args_list]
        assert "completed" in called_statuses

    @pytest.mark.unit
    async def test_emits_activity_with_summary(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.source_computer = None

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.is_threaded_output_enabled", return_value=False),
        ):
            mock_db.get_session = AsyncMock(return_value=_make_session())
            mock_db.update_session = AsyncMock()
            coord._record_agent_stop_input = AsyncMock()
            coord._record_agent_stop_output = AsyncMock(return_value=(None, "Summary text"))
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._maybe_send_incremental_output = AsyncMock(return_value=False)
            coord._finalize_agent_stop = AsyncMock()
            await coord.handle_agent_stop(context)

        coord._emit_activity_event.assert_called_once_with(
            "sess-001", AgentHookEvents.AGENT_STOP, summary="Summary text"
        )

    @pytest.mark.unit
    async def test_clears_last_tool_done_at(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.source_computer = None

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.is_threaded_output_enabled", return_value=False),
        ):
            mock_db.get_session = AsyncMock(return_value=_make_session())
            mock_db.update_session = AsyncMock()
            coord._record_agent_stop_input = AsyncMock()
            coord._record_agent_stop_output = AsyncMock(return_value=(None, None))
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._maybe_send_incremental_output = AsyncMock(return_value=False)
            coord._finalize_agent_stop = AsyncMock()
            await coord.handle_agent_stop(context)

        update_calls = mock_db.update_session.call_args_list
        assert any(c[1].get("last_tool_done_at") is None for c in update_calls)


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
            patch("teleclaude.core.agent_coordinator._coordinator.extract_tool_name", return_value="Bash"),
            patch("teleclaude.core.agent_coordinator._coordinator.build_tool_preview", return_value="$ ls"),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._clear_tool_use_skip = MagicMock()
            await coord.handle_tool_use(context)

        coord._emit_activity_event.assert_called_once_with(
            "sess-001", AgentHookEvents.TOOL_USE, "Bash", tool_preview="$ ls"
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
            coord._clear_tool_use_skip = MagicMock()
            await coord.handle_tool_use(context)

        called_statuses = [c[0][1] for c in coord._emit_status_event.call_args_list]
        assert "active_output" in called_statuses

    @pytest.mark.unit
    async def test_first_tool_use_records_in_db(self):
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
            coord._clear_tool_use_skip = MagicMock()
            await coord.handle_tool_use(context)

        mock_db.update_session.assert_called_once()
        call_kwargs = mock_db.update_session.call_args[1]
        assert "last_tool_use_at" in call_kwargs

    @pytest.mark.unit
    async def test_subsequent_tool_use_skips_db_write(self):
        coord = _make_coordinator()
        context = MagicMock()
        context.session_id = "sess-001"
        context.data.raw = {}
        session = _make_session(last_tool_use_at=datetime.now(UTC))

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.extract_tool_name", return_value=None),
            patch("teleclaude.core.agent_coordinator._coordinator.build_tool_preview", return_value=None),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            coord._emit_activity_event = MagicMock()
            coord._emit_status_event = MagicMock()
            coord._mark_tool_use_skip = MagicMock()
            await coord.handle_tool_use(context)

        mock_db.update_session.assert_not_called()
        coord._mark_tool_use_skip.assert_called_once_with("sess-001")


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


class TestRecordAgentStopInput:
    @pytest.mark.unit
    async def test_no_codex_input_skips_db_update(self):
        coord = _make_coordinator()
        session = _make_session()
        payload = MagicMock()
        coord._extract_user_input_for_codex = AsyncMock(return_value=None)

        with patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db:
            mock_db.update_session = AsyncMock()
            await coord._record_agent_stop_input("sess-001", payload, session)

        mock_db.update_session.assert_not_called()

    @pytest.mark.unit
    async def test_codex_input_updates_db(self):
        coord = _make_coordinator()
        session = _make_session()
        payload = MagicMock()
        now = datetime.now(UTC)
        coord._extract_user_input_for_codex = AsyncMock(return_value=("user typed this", now))

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator._is_codex_input_already_recorded", return_value=True),
        ):
            mock_db.update_session = AsyncMock()
            await coord._record_agent_stop_input("sess-001", payload, session)

        mock_db.update_session.assert_called_once()
        call_kwargs = mock_db.update_session.call_args[1]
        assert call_kwargs["last_message_sent"] == "user typed this"

    @pytest.mark.unit
    async def test_unrecorded_codex_input_emits_activity_and_broadcasts(self):
        coord = _make_coordinator()
        session = _make_session(lifecycle_status="active")
        payload = MagicMock()
        now = datetime.now(UTC)
        coord._extract_user_input_for_codex = AsyncMock(return_value=("user typed this", now))

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._coordinator._is_codex_input_already_recorded", return_value=False
            ),
            patch("teleclaude.core.agent_coordinator._coordinator._resolve_hook_actor_name", return_value="user"),
            patch("teleclaude.core.agent_coordinator._coordinator.config") as mock_config,
        ):
            mock_config.computer.name = "local"
            mock_db.update_session = AsyncMock()
            coord._emit_activity_event = MagicMock()
            coord.client.broadcast_user_input = AsyncMock()
            await coord._record_agent_stop_input("sess-001", payload, session)

        coord._emit_activity_event.assert_called_once_with("sess-001", AgentHookEvents.USER_PROMPT_SUBMIT)
        coord.client.broadcast_user_input.assert_called_once()


class TestRecordAgentStopOutput:
    @pytest.mark.unit
    async def test_no_raw_output_returns_none_link_and_summary(self):
        coord = _make_coordinator()
        payload = MagicMock()
        payload.raw = {}
        payload.prompt = None
        coord._extract_agent_output = AsyncMock(return_value=None)
        coord._summarize_output = AsyncMock(return_value=None)
        coord._speak_agent_stop_summary = AsyncMock()

        with patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db:
            mock_db.update_session = AsyncMock()
            link_output, summary = await coord._record_agent_stop_output("sess-001", payload)

        assert link_output is None
        assert summary is None
        mock_db.update_session.assert_not_called()

    @pytest.mark.unit
    async def test_raw_output_updates_db_and_calls_tts(self):
        coord = _make_coordinator()
        payload = MagicMock()
        payload.raw = {}
        payload.prompt = None
        coord._extract_agent_output = AsyncMock(return_value="Agent response here.")
        coord._summarize_output = AsyncMock(return_value="Short summary.")
        coord._speak_agent_stop_summary = AsyncMock()

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.config") as mock_config,
        ):
            mock_config.terminal.strip_ansi = False
            mock_db.update_session = AsyncMock()
            link_output, summary = await coord._record_agent_stop_output("sess-001", payload)

        assert link_output == "Agent response here."
        assert summary == "Short summary."
        mock_db.update_session.assert_called_once()
        coord._speak_agent_stop_summary.assert_called_once_with("sess-001", "Short summary.")

    @pytest.mark.unit
    async def test_checkpoint_prompt_nullifies_link_output(self):
        coord = _make_coordinator()
        payload = MagicMock()
        payload.raw = {}
        payload.prompt = "checkpoint-prompt"
        coord._extract_agent_output = AsyncMock(return_value="some output")
        coord._summarize_output = AsyncMock(return_value="summary")
        coord._speak_agent_stop_summary = AsyncMock()

        with (
            patch("teleclaude.core.agent_coordinator._coordinator.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._coordinator.config") as mock_config,
            patch("teleclaude.core.agent_coordinator._coordinator._is_checkpoint_prompt", return_value=True),
        ):
            mock_config.terminal.strip_ansi = False
            mock_db.update_session = AsyncMock()
            link_output, _ = await coord._record_agent_stop_output("sess-001", payload)

        assert link_output is None


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
        await coord._speak_agent_stop_summary("sess-001", "The task is done.")
        coord.tts_manager.speak.assert_called_once_with("The task is done.", session_id="sess-001")

    @pytest.mark.unit
    async def test_tts_exception_does_not_propagate(self):
        coord = _make_coordinator()
        coord.tts_manager.speak = AsyncMock(side_effect=RuntimeError("tts error"))
        # Should not raise — exception swallowing contract
        await coord._speak_agent_stop_summary("sess-001", "Some summary.")
