"""Characterization tests for teleclaude.adapters.ui_adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.constants import UI_MESSAGE_MAX_CHARS
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

    async def send_message(
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

    def _build_footer_metadata(self, session: Session) -> MessageMetadata:
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
    def test_threaded_output_default_is_false(self):
        assert UiAdapter.THREADED_OUTPUT is False

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
# Public boundary: move_badge_to_bottom
# ---------------------------------------------------------------------------


class TestMoveBadgeToBottom:
    @pytest.mark.unit
    async def test_cleans_footer_then_sends_new(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()
        with (
            patch.object(adapter, "_cleanup_footer_if_present", AsyncMock()) as cleanup_footer,
            patch.object(adapter, "_send_footer", AsyncMock(return_value="footer-id")) as send_footer,
        ):
            await adapter.move_badge_to_bottom(session)

        cleanup_footer.assert_awaited_once_with(session)
        send_footer.assert_awaited_once_with(session)


# ---------------------------------------------------------------------------
# Public boundary: clear_turn_state
# ---------------------------------------------------------------------------


class TestClearTurnState:
    @pytest.mark.unit
    async def test_clears_output_message_id_and_resets_char_offset(self, adapter: _ConcreteAdapter) -> None:
        session = _make_session()
        with (
            patch.object(adapter, "_clear_output_message_id", AsyncMock()) as clear_output,
            patch.object(adapter, "_set_char_offset", AsyncMock()) as set_char_offset,
        ):
            await adapter.clear_turn_state(session)

        clear_output.assert_awaited_once_with(session)
        set_char_offset.assert_awaited_once_with(session, 0)
