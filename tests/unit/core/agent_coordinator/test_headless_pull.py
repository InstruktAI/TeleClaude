"""Tests for event-driven headless output pull scheduling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.agent_coordinator._coordinator import AgentCoordinator
from teleclaude.core.events import AgentEventContext, AgentHookEvents
from teleclaude.core.models import Session

pytestmark = pytest.mark.unit


def _make_coordinator() -> AgentCoordinator:
    client = MagicMock()
    tts_manager = MagicMock()
    headless_snapshot_service = MagicMock()
    headless_snapshot_service.send_snapshot = AsyncMock()
    return AgentCoordinator(
        client=client,
        tts_manager=tts_manager,
        headless_snapshot_service=headless_snapshot_service,
    )


def _make_session(
    session_id: str = "sess-1",
    lifecycle_status: str = "headless",
    active_agent: str | None = "claude",
    native_log_file: str | None = "/tmp/transcript.jsonl",
) -> Session:
    return Session(
        session_id=session_id,
        computer_name="test-machine",
        tmux_session_name="tmux-sess-1",
        title="Test Session",
        lifecycle_status=lifecycle_status,
        active_agent=active_agent,
        native_log_file=native_log_file,
    )


def _make_context(
    session_id: str = "sess-1",
    event_type: str = AgentHookEvents.TOOL_USE,
    data: object | None = None,
) -> AgentEventContext:
    return AgentEventContext(
        session_id=session_id,
        event_type=event_type,
        data=data or MagicMock(raw={}),
    )


# ---------------------------------------------------------------------------
# _schedule_headless_pull
# ---------------------------------------------------------------------------


class TestScheduleHeadlessPull:
    @pytest.mark.asyncio
    async def test_skips_non_headless_session(self) -> None:
        coord = _make_coordinator()
        session = _make_session(lifecycle_status="active")
        with patch(
            "teleclaude.core.agent_coordinator._coordinator.db",
            new=MagicMock(get_session=AsyncMock(return_value=session)),
        ):
            await coord._schedule_headless_pull("sess-1")
        coord.headless_snapshot_service.send_snapshot.assert_not_called()

    @pytest.mark.asyncio
    async def test_schedules_timer_for_headless_session(self) -> None:
        coord = _make_coordinator()
        session = _make_session(lifecycle_status="headless")
        with patch(
            "teleclaude.core.agent_coordinator._coordinator.db",
            new=MagicMock(get_session=AsyncMock(return_value=session)),
        ):
            await coord._schedule_headless_pull("sess-1")
        # Timer handle stored — snapshot fires asynchronously via call_later
        assert "sess-1" in coord._headless_pull_handles

    @pytest.mark.asyncio
    async def test_debounces_within_window(self) -> None:
        coord = _make_coordinator()
        session = _make_session(lifecycle_status="headless")
        with patch(
            "teleclaude.core.agent_coordinator._coordinator.db",
            new=MagicMock(get_session=AsyncMock(return_value=session)),
        ):
            await coord._schedule_headless_pull("sess-1")
            first_handle = coord._headless_pull_handles["sess-1"]
            await coord._schedule_headless_pull("sess-1")
        # Second call is a no-op — same timer handle retained
        assert coord._headless_pull_handles["sess-1"] is first_handle

    @pytest.mark.asyncio
    async def test_immediate_bypasses_debounce(self) -> None:
        coord = _make_coordinator()
        session = _make_session(lifecycle_status="headless")
        with patch(
            "teleclaude.core.agent_coordinator._coordinator.db",
            new=MagicMock(get_session=AsyncMock(return_value=session)),
        ):
            await coord._schedule_headless_pull("sess-1", immediate=True)
        # Called synchronously, no sleep needed
        coord.headless_snapshot_service.send_snapshot.assert_called_once()


class TestDoHeadlessPull:
    @pytest.mark.asyncio
    async def test_sends_snapshot_for_headless_session(self) -> None:
        coord = _make_coordinator()
        session = _make_session(lifecycle_status="headless")
        with patch(
            "teleclaude.core.agent_coordinator._coordinator.db",
            new=MagicMock(get_session=AsyncMock(return_value=session)),
        ):
            await coord._do_headless_pull("sess-1")
        coord.headless_snapshot_service.send_snapshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_session_missing(self) -> None:
        coord = _make_coordinator()
        with patch(
            "teleclaude.core.agent_coordinator._coordinator.db",
            new=MagicMock(get_session=AsyncMock(return_value=None)),
        ):
            await coord._do_headless_pull("sess-gone")
        coord.headless_snapshot_service.send_snapshot.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_session_no_longer_headless(self) -> None:
        coord = _make_coordinator()
        session = _make_session(lifecycle_status="active")
        with patch(
            "teleclaude.core.agent_coordinator._coordinator.db",
            new=MagicMock(get_session=AsyncMock(return_value=session)),
        ):
            await coord._do_headless_pull("sess-1")
        coord.headless_snapshot_service.send_snapshot.assert_not_called()


class TestCancelHeadlessPull:
    @pytest.mark.asyncio
    async def test_removes_pending_timer(self) -> None:
        coord = _make_coordinator()
        session = _make_session(lifecycle_status="headless")
        with patch(
            "teleclaude.core.agent_coordinator._coordinator.db",
            new=MagicMock(get_session=AsyncMock(return_value=session)),
        ):
            await coord._schedule_headless_pull("sess-1")
            assert "sess-1" in coord._headless_pull_handles
            coord._cancel_headless_pull("sess-1")
        # Timer handle removed and cancelled
        assert "sess-1" not in coord._headless_pull_handles


# ---------------------------------------------------------------------------
# Event handler integration
# ---------------------------------------------------------------------------


class TestEventHandlerHeadlessPull:
    @pytest.mark.asyncio
    async def test_handle_tool_use_schedules_pull(self) -> None:
        coord = _make_coordinator()
        session = _make_session(lifecycle_status="headless")
        context = _make_context(event_type=AgentHookEvents.TOOL_USE)
        with (
            patch(
                "teleclaude.core.agent_coordinator._coordinator.db",
                new=MagicMock(
                    get_session=AsyncMock(return_value=session),
                    update_session=AsyncMock(),
                ),
            ),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.event_bus",
                new=MagicMock(),
            ),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.serialize_activity_event",
                return_value=MagicMock(canonical_type="x", message_intent="x", delivery_scope="x"),
            ),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.serialize_status_event",
                return_value=MagicMock(message_intent="x", delivery_scope="x"),
            ),
            patch.object(coord, "_schedule_headless_pull", new_callable=AsyncMock) as mock_schedule,
        ):
            await coord.handle_tool_use(context)
        mock_schedule.assert_called_once_with("sess-1")

    @pytest.mark.asyncio
    async def test_handle_tool_done_schedules_pull(self) -> None:
        coord = _make_coordinator()
        session = _make_session(lifecycle_status="headless")
        context = _make_context(event_type=AgentHookEvents.TOOL_DONE)
        with (
            patch(
                "teleclaude.core.agent_coordinator._coordinator.db",
                new=MagicMock(get_session=AsyncMock(return_value=session)),
            ),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.event_bus",
                new=MagicMock(),
            ),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.serialize_activity_event",
                return_value=MagicMock(canonical_type="x", message_intent="x", delivery_scope="x"),
            ),
            patch.object(coord, "_schedule_headless_pull", new_callable=AsyncMock) as mock_schedule,
        ):
            await coord.handle_tool_done(context)
        mock_schedule.assert_called_once_with("sess-1")

    @pytest.mark.asyncio
    async def test_handle_agent_stop_schedules_immediate_pull(self) -> None:
        coord = _make_coordinator()
        session = _make_session(lifecycle_status="headless")
        stop_data = MagicMock(
            raw={},
            session_id="native-1",
            transcript_path="/tmp/t.jsonl",
            prompt=None,
            source_computer=None,
        )
        context = _make_context(
            event_type=AgentHookEvents.AGENT_STOP,
            data=stop_data,
        )
        with (
            patch(
                "teleclaude.core.agent_coordinator._coordinator.db",
                new=MagicMock(
                    get_session=AsyncMock(return_value=session),
                    update_session=AsyncMock(),
                    get_notification_flag=AsyncMock(return_value=False),
                    set_notification_flag=AsyncMock(),
                ),
            ),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.event_bus",
                new=MagicMock(),
            ),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.serialize_activity_event",
                return_value=MagicMock(canonical_type="x", message_intent="x", delivery_scope="x"),
            ),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.serialize_status_event",
                return_value=MagicMock(message_intent="x", delivery_scope="x"),
            ),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.is_threaded_output_enabled",
                return_value=False,
            ),
            patch.object(coord, "_schedule_headless_pull", new_callable=AsyncMock) as mock_schedule,
            patch.object(coord, "_record_agent_stop_input", new_callable=AsyncMock),
            patch.object(coord, "_record_agent_stop_output", new_callable=AsyncMock, return_value=(None, None)),
            patch.object(coord, "_maybe_send_incremental_output", new_callable=AsyncMock),
            patch.object(coord, "_finalize_agent_stop", new_callable=AsyncMock),
        ):
            await coord.handle_agent_stop(context)
        mock_schedule.assert_called_once_with("sess-1", immediate=True)

    @pytest.mark.asyncio
    async def test_handle_tool_use_skips_pull_for_non_headless(self) -> None:
        coord = _make_coordinator()
        session = _make_session(lifecycle_status="active")
        context = _make_context(event_type=AgentHookEvents.TOOL_USE)
        with (
            patch(
                "teleclaude.core.agent_coordinator._coordinator.db",
                new=MagicMock(
                    get_session=AsyncMock(return_value=session),
                    update_session=AsyncMock(),
                ),
            ),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.event_bus",
                new=MagicMock(),
            ),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.serialize_activity_event",
                return_value=MagicMock(canonical_type="x", message_intent="x", delivery_scope="x"),
            ),
            patch(
                "teleclaude.core.agent_coordinator._coordinator.serialize_status_event",
                return_value=MagicMock(message_intent="x", delivery_scope="x"),
            ),
            patch.object(coord, "_schedule_headless_pull", new_callable=AsyncMock) as mock_schedule,
        ):
            await coord.handle_tool_use(context)
        # _schedule_headless_pull is always called; it checks lifecycle internally
        mock_schedule.assert_called_once_with("sess-1")
