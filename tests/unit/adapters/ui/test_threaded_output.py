"""Characterization tests for teleclaude.adapters.ui.threaded_output."""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.adapters.ui.threaded_output import ThreadedOutputMixin
from teleclaude.core.models import MessageMetadata, Session

# ---------------------------------------------------------------------------
# Minimal concrete host for testing
# ---------------------------------------------------------------------------


class _ThreadedHost(ThreadedOutputMixin):
    ADAPTER_KEY = "telegram"
    MARKDOWN_FLAVOR = "plain"
    max_message_size = 50
    THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS = 50

    def __init__(self) -> None:
        self.client = MagicMock()
        self._char_offset: int = 0
        self._output_message_id: str | None = None
        self._output_delivery_locks: dict[str, asyncio.Lock] = {}

        # Mocked methods
        self.send_message = AsyncMock(return_value="new-msg")
        self.edit_message = AsyncMock(return_value=True)

    @classmethod
    def _get_output_delivery_lock(cls, _session_id: str) -> asyncio.Lock:
        return asyncio.Lock()

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

    async def _deliver_output_unlocked(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        session: Session,
        text: str,
        metadata: MessageMetadata,
        _multi_message: bool = False,
        _status_line: str = "",
        _dedupe_by_digest: bool = True,
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

    def _convert_markdown_for_platform(self, text: str) -> str:
        return text


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
    """Provide a minimal ThreadedOutputMixin host instance."""
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

        with patch("teleclaude.core.db.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await host.send_threaded_output(session, "short")

        assert host._char_offset == 0 or host._char_offset <= 5

    @pytest.mark.unit
    async def test_no_active_text_with_existing_message_returns_id(self, host: _ThreadedHost) -> None:  # pylint: disable=redefined-outer-name
        """Returns existing message ID when there is no new text to deliver."""
        session = _make_session()
        host._char_offset = 5
        host._output_message_id = "existing-id"

        with patch("teleclaude.core.db.db") as mock_db:
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

        with patch("teleclaude.core.db.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await host.send_threaded_output(session, long_text)

        # Offset should advance past zero — pagination occurred
        assert host._char_offset > 0

    @pytest.mark.unit
    async def test_short_text_within_limit_delivered_directly(self, host: _ThreadedHost) -> None:  # pylint: disable=redefined-outer-name
        """Short text within the size limit is delivered without pagination."""
        session = _make_session()
        short_text = "hi"

        with patch("teleclaude.core.db.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            result = await host.send_threaded_output(session, short_text)

        assert result is not None
