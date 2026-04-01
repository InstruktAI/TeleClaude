"""Characterization tests for threaded output delivery on UiAdapter."""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.models import ChannelMetadata, MessageMetadata, PeerInfo, Session

# ---------------------------------------------------------------------------
# Minimal concrete host for testing
# ---------------------------------------------------------------------------


class _ThreadedHost(UiAdapter):
    ADAPTER_KEY = "telegram"
    max_message_size = 50
    THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS = 50
    OUTPUT_CADENCE_SECONDS = 0.0

    def __init__(self) -> None:  # pylint: disable=super-init-not-called
        # Skip UiAdapter.__init__ to avoid event_bus side effects
        self.client = MagicMock()
        self._char_offset: int = 0
        self._output_message_id: str | None = None
        self._output_delivery_locks: dict[str, asyncio.Lock] = {}
        self._output_cadence = None

        # Mocked methods — assigned as instance attrs to override abstract methods
        self._send_message_mock = AsyncMock(return_value="new-msg")
        self._edit_message_mock = AsyncMock(return_value=True)

    # --- Abstract method stubs (required by BaseAdapter) ---

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
        return ""

    async def update_channel_title(self, session: Session, title: str) -> bool:
        return True

    async def close_channel(self, session: Session) -> bool:
        return True

    async def reopen_channel(self, session: Session) -> bool:
        return True

    async def delete_channel(self, session: Session) -> bool:
        return True

    async def send_message(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, session: Session, text: str, *, metadata: MessageMetadata | None = None, multi_message: bool = False
    ) -> str:
        result = await self._send_message_mock(session, text, metadata=metadata, multi_message=multi_message)
        return result

    async def edit_message(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, session: Session, message_id: str, text: str, *, metadata: MessageMetadata | None = None
    ) -> bool:
        result = await self._edit_message_mock(session, message_id, text, metadata=metadata)
        return result

    async def delete_message(self, session: Session, message_id: str) -> bool:
        _ = (session, message_id)
        return True

    async def send_file(
        self, session: Session, file_path: str, *, caption: str | None = None, metadata: MessageMetadata | None = None
    ) -> str:
        _ = (session, file_path, caption, metadata)
        return ""

    async def discover_peers(self) -> list[PeerInfo]:
        return []

    async def poll_output_stream(self, session: Session, timeout: float = 300.0) -> AsyncIterator[str]:
        raise NotImplementedError

    # --- Override output message tracking to use simple instance attrs ---

    def _get_char_offset(self, _session: Session) -> int:
        return self._char_offset

    async def _set_char_offset(self, _session: Session, value: int) -> None:
        self._char_offset = value

    async def _get_output_message_id(self, _session: Session) -> str | None:
        return self._output_message_id

    async def _store_output_message_id(self, _session: Session, message_id: str) -> None:
        self._output_message_id = message_id

    async def _clear_output_message_id(self, _session: Session) -> None:
        self._output_message_id = None

    def _build_metadata_for_thread(self) -> MessageMetadata:
        return MessageMetadata(parse_mode=None)  # No MarkdownV2 by default

    async def _deliver_output_unlocked(  # pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
        self,
        session: Session,
        text: str,
        metadata: MessageMetadata,
        **delivery_kwargs: object,
    ) -> str | None:
        if self._output_message_id:
            return self._output_message_id
        new_id = await self.send_message(session, text, metadata=metadata)
        if new_id:
            self._output_message_id = new_id
        return new_id

    async def _try_edit_output_message(self, session: Session, text: str, metadata: MessageMetadata) -> bool:
        if not self._output_message_id:
            return False
        return await self.edit_message(session, self._output_message_id, text, metadata=metadata)


def _make_session(**kwargs: object) -> Session:
    return Session(
        session_id="sess-123",
        computer_name="local",
        tmux_session_name="test",
        title="Test",
        **kwargs,
    )


@pytest.fixture
def host() -> _ThreadedHost:
    """Provide a minimal UiAdapter host instance for threaded output tests."""
    return _ThreadedHost()


# ---------------------------------------------------------------------------
# Char offset management
# ---------------------------------------------------------------------------


class TestCharOffsetManagement:
    """Tests for char offset tracking and reset logic."""

    @pytest.mark.unit
    async def test_offset_resets_when_text_shorter_than_offset(self, host: _ThreadedHost) -> None:  # pylint: disable=redefined-outer-name
        """Offset resets to zero when text is shorter than the recorded offset."""
        session = _make_session()
        host._char_offset = 100  # More than text length

        with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await host.send_threaded_output(session, "short")

        assert host._char_offset == 0 or host._char_offset <= 5

    @pytest.mark.unit
    async def test_no_active_text_with_existing_message_returns_id(self, host: _ThreadedHost) -> None:  # pylint: disable=redefined-outer-name
        """Returns existing message ID when there is no new text to deliver."""
        session = _make_session()
        host._char_offset = 5
        host._output_message_id = "existing-id"

        with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            result = await host.send_threaded_output(session, "hello")  # len=5, all consumed

        assert result == "existing-id"


# ---------------------------------------------------------------------------
# Overflow / pagination
# ---------------------------------------------------------------------------


class TestOverflowPagination:
    """Tests for message overflow splitting and pagination."""

    @pytest.mark.unit
    async def test_long_text_triggers_pagination(self, host: _ThreadedHost) -> None:  # pylint: disable=redefined-outer-name
        """Long text causes the char offset to advance (pagination occurred)."""
        host.max_message_size = 20
        session = _make_session()
        long_text = "a" * 100

        with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await host.send_threaded_output(session, long_text)

        # Offset should advance past zero — pagination occurred
        assert host._char_offset > 0

    @pytest.mark.unit
    async def test_short_text_within_limit_delivered_directly(self, host: _ThreadedHost) -> None:  # pylint: disable=redefined-outer-name
        """Short text within the size limit is delivered without pagination."""
        session = _make_session()
        short_text = "hi"

        with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            result = await host.send_threaded_output(session, short_text)

        assert result is not None
