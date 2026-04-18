"""Characterization tests for teleclaude.adapters.ui_adapter."""
# pylint: disable=protected-access,invalid-name,unused-argument,unreachable,use-implicit-booleaness-not-comparison

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.adapters.qos.action_throttler import AdapterActionThrottler
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core.events import SessionStatusContext, SessionTitleChangedContext
from teleclaude.core.models import (
    ChannelMetadata,
    CleanupTrigger,
    MessageMetadata,
    PeerInfo,
    Session,
)

# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing (UiAdapter is abstract in spirit)
# ---------------------------------------------------------------------------


class _ConcreteAdapter(UiAdapter):
    """Minimal UiAdapter subclass with required abstract methods stubbed."""

    ADAPTER_KEY = "telegram"

    async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
        return "chan1"

    async def update_channel_title(self, session: Session, title: str) -> bool:
        return True

    async def close_channel(self, session: Session) -> bool:
        return True

    async def reopen_channel(self, session: Session) -> bool:
        return True

    async def delete_channel(self, session: Session) -> bool:
        return True

    async def send_message(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        session: Session,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
        cleanup_trigger: CleanupTrigger | None = None,
        ephemeral: bool = True,
    ) -> str | None:
        return "msg-1"

    async def edit_message(
        self,
        session: Session,
        message_id: str,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> bool:
        return True

    async def delete_message(self, session: Session, message_id: str) -> bool:
        return True

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_file(
        self,
        session: Session,
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        return "file-msg"

    async def discover_peers(self) -> list[PeerInfo]:
        return []

    async def poll_output_stream(  # type: ignore[override]
        self, session: Session, timeout: float = 300.0
    ) -> AsyncIterator[str]:
        raise NotImplementedError
        yield ""  # pragma: no cover

    def _metadata(self, **kwargs: Any) -> MessageMetadata:
        return MessageMetadata()


def _make_session(**kwargs: object) -> Session:
    defaults: dict[str, object] = {  # guard: loose-dict - test helper, values are mixed Session field types
        "session_id": "sess-abc",
        "computer_name": "local",
        "tmux_session_name": "test",
        "title": "Test",
    }
    defaults.update(kwargs)
    return Session(**defaults)


@pytest.fixture
def client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def adapter(client: MagicMock) -> _ConcreteAdapter:
    with patch("teleclaude.adapters.ui_adapter.event_bus"):
        inst = _ConcreteAdapter(client)
    inst._action_throttler = AdapterActionThrottler()
    return inst


# ---------------------------------------------------------------------------
# Class-level attributes
# ---------------------------------------------------------------------------


class TestUiAdapterDefaults:
    @pytest.mark.unit
    def test_default_adapter_key_on_base(self):
        # The base class default is "unknown"; subclass overrides it
        assert UiAdapter.ADAPTER_KEY == "unknown"

    @pytest.mark.unit
    def test_max_message_size_equals_constant(self):
        assert UiAdapter.max_message_size == UI_MESSAGE_MAX_CHARS

    @pytest.mark.unit
    def test_command_handler_overrides_empty(self):
        assert UiAdapter.COMMAND_HANDLER_OVERRIDES == {}


# ---------------------------------------------------------------------------
# Output delivery lock
# ---------------------------------------------------------------------------


class TestGetOutputDeliveryLock:
    @pytest.mark.unit
    def test_returns_asyncio_lock(self, adapter: _ConcreteAdapter) -> None:
        lock = adapter._get_output_delivery_lock("sess-1")
        assert isinstance(lock, asyncio.Lock)

    @pytest.mark.unit
    def test_same_session_returns_same_lock(self, adapter: _ConcreteAdapter) -> None:
        lock1 = adapter._get_output_delivery_lock("sess-1")
        lock2 = adapter._get_output_delivery_lock("sess-1")
        assert lock1 is lock2

    @pytest.mark.unit
    def test_different_sessions_get_different_locks(self, adapter: _ConcreteAdapter) -> None:
        lock1 = adapter._get_output_delivery_lock("sess-1")
        lock2 = adapter._get_output_delivery_lock("sess-2")
        assert lock1 is not lock2


# ---------------------------------------------------------------------------
# Static / pure helpers
# ---------------------------------------------------------------------------


class TestFitsBudget:
    @pytest.mark.unit
    def test_text_within_budget_returns_true(self):
        assert UiAdapter._fits_budget("hello", 100) is True

    @pytest.mark.unit
    def test_text_at_budget_returns_true(self):
        text = "a" * 10
        assert UiAdapter._fits_budget(text, 10) is True

    @pytest.mark.unit
    def test_text_over_budget_returns_false(self):
        text = "a" * 11
        assert UiAdapter._fits_budget(text, 10) is False

    @pytest.mark.unit
    def test_multibyte_characters_counted_by_bytes(self):
        # "€" is 3 bytes in UTF-8; budget of 2 bytes should fail
        assert UiAdapter._fits_budget("€", 2) is False
        assert UiAdapter._fits_budget("€", 3) is True


class TestNoOpMethods:
    @pytest.mark.unit
    async def test_cleanup_stale_resources_returns_zero(self, adapter: _ConcreteAdapter) -> None:
        result = await adapter.cleanup_stale_resources()
        assert result == 0

    @pytest.mark.unit
    async def test_ensure_channel_returns_session(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()
        result = await adapter.ensure_channel(session)
        assert result is session

    @pytest.mark.unit
    async def test_ensure_output_lane_ready_skips_channel_ensure_for_tmux_activity(
        self, adapter: _ConcreteAdapter
    ) -> None:
        session = _make_session()
        with patch.object(adapter, "ensure_channel", AsyncMock(return_value=session)) as ensure_channel:
            result = await adapter.ensure_output_lane_ready(session, trigger="tmux_activity")

        assert result is session
        ensure_channel.assert_not_awaited()

    @pytest.mark.unit
    async def test_ensure_output_lane_ready_delegates_for_non_tmux_triggers(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()
        with patch.object(adapter, "ensure_channel", AsyncMock(return_value=session)) as ensure_channel:
            result = await adapter.ensure_output_lane_ready(session, trigger="repair")

        assert result is session
        ensure_channel.assert_awaited_once_with(session)

    @pytest.mark.unit
    def test_drop_pending_output_returns_zero(self, adapter: _ConcreteAdapter) -> None:
        result = adapter.drop_pending_output("sess-x")
        assert result == 0

    @pytest.mark.unit
    async def test_recover_lane_error_re_raises(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()
        error = ValueError("test error")
        with pytest.raises(ValueError, match="test error"):
            await adapter.recover_lane_error(session, error, AsyncMock(), "title")

    @pytest.mark.unit
    async def test_send_typing_indicator_is_noop(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()
        # Should not raise
        await adapter.send_typing_indicator(session)

    @pytest.mark.unit
    def test_convert_markdown_for_platform_identity(self, adapter: _ConcreteAdapter) -> None:
        text = "**bold** _italic_"
        assert adapter._convert_markdown_for_platform(text) == text


# ---------------------------------------------------------------------------
# char offset (unknown adapter key → 0)
# ---------------------------------------------------------------------------


class TestGetCharOffset:
    @pytest.mark.unit
    def test_unknown_adapter_returns_zero(self) -> None:
        with patch("teleclaude.adapters.ui_adapter.event_bus"):
            adapter = _ConcreteAdapter.__new__(_ConcreteAdapter)
            adapter.ADAPTER_KEY = "unknown"
            adapter.client = MagicMock()
        session = _make_session()
        assert adapter._get_char_offset(session) == 0


# ---------------------------------------------------------------------------
# Session badge on accepted
# ---------------------------------------------------------------------------


class TestSendSessionBadge:
    @pytest.mark.unit
    async def test_badge_sends_session_id_lines(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()
        with patch.object(adapter, "send_message", AsyncMock(return_value="badge-msg")) as send_msg:
            await adapter._send_session_badge(session)

        send_msg.assert_awaited_once()
        call_args = send_msg.await_args
        assert call_args is not None
        assert session.session_id in call_args.args[1]
        assert call_args.kwargs["metadata"].parse_mode is None

    @pytest.mark.unit
    async def test_badge_skips_when_no_session_id_lines(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()
        with (
            patch.object(adapter, "_build_session_id_lines", return_value=""),
            patch.object(adapter, "send_message", AsyncMock()) as send_msg,
        ):
            await adapter._send_session_badge(session)

        send_msg.assert_not_awaited()


class TestHandleSessionStatus:
    @pytest.mark.unit
    async def test_active_status_sends_typing_indicator(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()
        context = SessionStatusContext(
            session_id=session.session_id,
            status="active",
            reason="agent_session_started",
            timestamp="2026-04-11T00:00:00+00:00",
        )

        with (
            patch("teleclaude.adapters.ui_adapter.db.get_session", AsyncMock(return_value=session)),
            patch.object(adapter, "send_typing_indicator", AsyncMock()) as send_typing_indicator,
        ):
            await adapter._handle_session_status("session_status", context)

        send_typing_indicator.assert_awaited_once_with(session)

    @pytest.mark.unit
    async def test_active_output_status_does_not_send_typing_indicator(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()
        context = SessionStatusContext(
            session_id=session.session_id,
            status="active_output",
            reason="output_observed",
            timestamp="2026-04-11T00:00:00+00:00",
        )

        with (
            patch("teleclaude.adapters.ui_adapter.db.get_session", AsyncMock(return_value=session)),
            patch.object(adapter, "send_typing_indicator", AsyncMock()) as send_typing_indicator,
        ):
            await adapter._handle_session_status("session_status", context)

        send_typing_indicator.assert_not_awaited()

    @pytest.mark.unit
    async def test_accepted_status_badge_still_sends_when_typing_is_throttled(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()
        context = SessionStatusContext(
            session_id=session.session_id,
            status="accepted",
            reason="user_prompt_accepted",
            timestamp="2026-04-11T00:00:00+00:00",
        )
        adapter._action_throttler.allow(
            f"{adapter.ADAPTER_KEY}:{session.session_id}:typing",
            min_interval_s=adapter.get_action_throttle_interval_s("typing"),
            now=100.0,
        )

        with (
            patch("teleclaude.adapters.ui_adapter.db.get_session", AsyncMock(return_value=session)),
            patch("teleclaude.adapters.ui_adapter.time.monotonic", return_value=101.0),
            patch.object(adapter, "send_typing_indicator", AsyncMock()) as send_typing_indicator,
            patch.object(adapter, "_send_session_badge", AsyncMock()) as send_session_badge,
        ):
            await adapter._handle_session_status("session_status", context)

        send_typing_indicator.assert_not_awaited()
        send_session_badge.assert_awaited_once_with(session)


class TestHandleSessionTitleChanged:
    @pytest.mark.unit
    async def test_title_event_queues_latest_title(self, adapter: _ConcreteAdapter) -> None:
        with patch.object(adapter, "request_title_sync", AsyncMock()) as request_title_sync:
            await adapter._handle_session_title_changed(
                "session_title_changed",
                SessionTitleChangedContext(session_id="sess-abc", title="Renamed"),
            )

        request_title_sync.assert_awaited_once_with("sess-abc", "Renamed")

    @pytest.mark.unit
    async def test_title_lane_coalesces_to_latest_pending_title(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session(session_id="sess-title-lane")
        started = asyncio.Event()
        release = asyncio.Event()

        async def update_title(_session: Session, _title: str) -> bool:
            started.set()
            await release.wait()
            return True

        with (
            patch("teleclaude.adapters.ui_adapter.db.get_session", AsyncMock(return_value=session)),
            patch.object(adapter, "update_channel_title", AsyncMock(side_effect=update_title)) as update_channel_title,
        ):
            await adapter.request_title_sync(session.session_id, "First")
            await started.wait()
            await adapter.request_title_sync(session.session_id, "Final")
            release.set()
            task = adapter._title_sync_tasks[session.session_id]
            await task

        assert update_channel_title.await_args_list[0].args == (session, "First")
        assert update_channel_title.await_args_list[1].args == (session, "Final")


# ---------------------------------------------------------------------------
# Public boundary: clear_turn_state
# ---------------------------------------------------------------------------


class TestClearTurnState:
    @pytest.mark.unit
    async def test_resets_char_offset_and_clears_output_message_id(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()
        with (
            patch.object(adapter, "_set_char_offset", AsyncMock()) as set_char_offset,
            patch.object(adapter, "_set_origin_field", AsyncMock()) as set_origin_field,
        ):
            await adapter.clear_turn_state(session)

        set_char_offset.assert_awaited_once_with(session, 0)
        set_origin_field.assert_awaited_once()
        call_kwargs = set_origin_field.await_args[1]
        assert call_kwargs["output_message_id"] is None
        assert "last_delivered_at" in call_kwargs


class TestSendThreadedOutput:
    @pytest.mark.unit
    async def test_stamps_last_delivered_at_after_successful_delivery(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()
        delivery_ts = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)

        with (
            patch.object(adapter, "_sync_threaded_session_state", AsyncMock()),
            patch.object(adapter, "_send_threaded_output_unlocked", AsyncMock(return_value="msg-1")),
            patch.object(adapter, "set_last_delivered_at", AsyncMock()) as set_last_delivered_at,
        ):
            result = await adapter.send_threaded_output(session, "content", delivery_ts=delivery_ts)

        assert result == "msg-1"
        set_last_delivered_at.assert_awaited_once_with(session, delivery_ts)


# ---------------------------------------------------------------------------
# Turn boundary detection in send_output_update
# ---------------------------------------------------------------------------


class TestMaybeClearOnTurnBoundary:
    """The adapter must detect a new turn and reset delivery state.

    Without this, the polling coordinator reuses a stale output_message_id
    across turns, so each turn's content silently overwrites the previous
    one and overflow chunk 1 lands in a buried (invisible) message.
    """

    @pytest.mark.unit
    async def test_first_delivery_records_anchor_without_clearing(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session(native_log_file="/tmp/log", active_agent="claude")
        ts = datetime(2026, 4, 10, 14, 0, 0, tzinfo=UTC)

        with (
            patch(
                "teleclaude.adapters.ui_adapter.extract_last_turn_boundary_timestamp",
                return_value=ts,
            ),
            patch.object(adapter, "_origin_field", return_value=None),
            patch.object(adapter, "clear_turn_state", AsyncMock()) as clear_state,
            patch.object(adapter, "_set_origin_field", AsyncMock()) as set_origin_field,
        ):
            await adapter._maybe_clear_on_turn_boundary(session)

        clear_state.assert_not_awaited()
        set_origin_field.assert_awaited_once_with(session, turn_anchor_ts=ts.isoformat())

    @pytest.mark.unit
    async def test_same_turn_does_not_clear(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session(native_log_file="/tmp/log", active_agent="claude")
        ts = datetime(2026, 4, 10, 14, 0, 0, tzinfo=UTC)

        with (
            patch(
                "teleclaude.adapters.ui_adapter.extract_last_turn_boundary_timestamp",
                return_value=ts,
            ),
            patch.object(adapter, "_origin_field", return_value=ts.isoformat()),
            patch.object(adapter, "clear_turn_state", AsyncMock()) as clear_state,
            patch.object(adapter, "_set_origin_field", AsyncMock()) as set_origin_field,
        ):
            await adapter._maybe_clear_on_turn_boundary(session)

        clear_state.assert_not_awaited()
        set_origin_field.assert_not_awaited()

    @pytest.mark.unit
    async def test_new_turn_clears_state_and_advances_anchor(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session(native_log_file="/tmp/log", active_agent="claude")
        previous = datetime(2026, 4, 10, 14, 0, 0, tzinfo=UTC)
        latest = datetime(2026, 4, 10, 14, 5, 0, tzinfo=UTC)

        with (
            patch(
                "teleclaude.adapters.ui_adapter.extract_last_turn_boundary_timestamp",
                return_value=latest,
            ),
            patch.object(adapter, "_origin_field", return_value=previous.isoformat()),
            patch.object(adapter, "clear_turn_state", AsyncMock()) as clear_state,
            patch.object(adapter, "_set_origin_field", AsyncMock()) as set_origin_field,
        ):
            await adapter._maybe_clear_on_turn_boundary(session)

        clear_state.assert_awaited_once_with(session)
        set_origin_field.assert_awaited_once_with(session, turn_anchor_ts=latest.isoformat())

    @pytest.mark.unit
    async def test_no_user_message_is_noop(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session(native_log_file="/tmp/log", active_agent="claude")

        with (
            patch(
                "teleclaude.adapters.ui_adapter.extract_last_turn_boundary_timestamp",
                return_value=None,
            ),
            patch.object(adapter, "clear_turn_state", AsyncMock()) as clear_state,
            patch.object(adapter, "_set_origin_field", AsyncMock()) as set_origin_field,
        ):
            await adapter._maybe_clear_on_turn_boundary(session)

        clear_state.assert_not_awaited()
        set_origin_field.assert_not_awaited()

    @pytest.mark.unit
    async def test_missing_transcript_or_agent_is_noop(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()  # no native_log_file, no active_agent

        with (
            patch(
                "teleclaude.adapters.ui_adapter.extract_last_turn_boundary_timestamp",
            ) as extract,
            patch.object(adapter, "clear_turn_state", AsyncMock()) as clear_state,
        ):
            await adapter._maybe_clear_on_turn_boundary(session)

        extract.assert_not_called()
        clear_state.assert_not_awaited()

    @pytest.mark.unit
    async def test_send_output_update_runs_turn_boundary_check_before_delivery(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()
        calls: list[str] = []

        async def record_boundary(_session: Session) -> None:
            calls.append("boundary")

        async def record_threaded(*_args: object, **_kwargs: object) -> str:
            calls.append("threaded")
            return "msg-1"

        with (
            patch.object(adapter, "_maybe_clear_on_turn_boundary", AsyncMock(side_effect=record_boundary)),
            patch.object(adapter, "send_threaded_output", AsyncMock(side_effect=record_threaded)),
        ):
            result = await adapter.send_output_update(session, "body", 0.0, 0.0)

        assert result == "msg-1"
        assert calls == ["boundary", "threaded"]


# ---------------------------------------------------------------------------
# Projection boundary: UI adapters must not write canonical conversation state
# ---------------------------------------------------------------------------


class TestDispatchCommandBoundary:
    """UI adapters must not write last_input_origin or canonical conversation state."""

    @pytest.mark.unit
    async def test_dispatch_command_does_not_write_last_input_origin(self, adapter: _ConcreteAdapter) -> None:
        """last_input_origin ownership belongs to acceptance handlers, not UI dispatch."""
        session = _make_session()
        metadata = MessageMetadata(origin="telegram")
        adapter.client.adapters = {"telegram": MagicMock()}
        adapter.client.pre_handle_command = AsyncMock()
        adapter.client.post_handle_command = AsyncMock()
        handler = AsyncMock(return_value=None)

        with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
            mock_db.update_session = AsyncMock()
            await adapter._dispatch_command(session, "msg-1", metadata, "test_cmd", {}, handler)

        # The UI adapter must not write last_input_origin
        for call in mock_db.update_session.call_args_list:
            assert "last_input_origin" not in call.kwargs, (
                "UI adapter must not write last_input_origin — acceptance handlers own this field"
            )

    @pytest.mark.unit
    async def test_dispatch_command_does_not_write_canonical_conversation_state(
        self, adapter: _ConcreteAdapter
    ) -> None:
        """UI adapter must not write last_message_sent or last_message_sent_at."""
        session = _make_session()
        metadata = MessageMetadata(origin="telegram")
        adapter.client.adapters = {"telegram": MagicMock()}
        adapter.client.pre_handle_command = AsyncMock()
        adapter.client.post_handle_command = AsyncMock()
        handler = AsyncMock(return_value=None)

        with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
            mock_db.update_session = AsyncMock()
            await adapter._dispatch_command(session, "msg-1", metadata, "send_message", {"text": "hello"}, handler)

        for call in mock_db.update_session.call_args_list:
            assert "last_message_sent" not in call.kwargs, (
                "UI adapter must not write last_message_sent — projection owns canonical state"
            )
            assert "last_message_sent_at" not in call.kwargs, (
                "UI adapter must not write last_message_sent_at — projection owns canonical state"
            )
