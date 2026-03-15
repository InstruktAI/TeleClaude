"""Characterization tests for teleclaude.adapters.ui.threaded_output."""

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
    THREADED_OUTPUT = True
    ADAPTER_KEY = "telegram"
    max_message_size = 50
    THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS = 50

    def __init__(self):
        self.client = MagicMock()
        self.client.send_message = AsyncMock(return_value="badge-msg")
        self._char_offset: int = 0
        self._output_message_id: str | None = None
        self._badge_sent: bool = False
        self._footer_cleaned: bool = False
        self._output_delivery_locks: dict[str, asyncio.Lock] = {}

        # Mocked methods
        self.send_message = AsyncMock(return_value="new-msg")
        self.edit_message = AsyncMock(return_value=True)

    @classmethod
    def _get_output_delivery_lock(cls, session_id: str) -> asyncio.Lock:
        return asyncio.Lock()

    def _get_char_offset(self, session: Session) -> int:
        return self._char_offset

    async def _set_char_offset(self, session: Session, value: int) -> None:
        self._char_offset = value

    async def _get_output_message_id(self, session: Session) -> str | None:
        return self._output_message_id

    async def _store_output_message_id(self, session: Session, message_id: str) -> None:
        self._output_message_id = message_id

    async def _clear_output_message_id(self, session: Session) -> None:
        self._output_message_id = None

    async def _cleanup_footer_if_present(self, session: Session) -> None:
        self._footer_cleaned = True

    async def _get_badge_sent(self, session: Session) -> bool:
        return self._badge_sent

    async def _set_badge_sent(self, session: Session, value: bool) -> None:
        self._badge_sent = value

    def _build_metadata_for_thread(self) -> MessageMetadata:
        return MessageMetadata(parse_mode=None)  # No MarkdownV2 by default

    async def _deliver_output_unlocked(
        self,
        session: Session,
        text: str,
        metadata: MessageMetadata,
        multi_message: bool = False,
        status_line: str = "",
        dedupe_by_digest: bool = True,
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

    def _build_session_id_lines(self, session: Session) -> str:
        return f"📋 tc: {session.session_id}"

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
    return _ThreadedHost()


# ---------------------------------------------------------------------------
# send_threaded_output gate: THREADED_OUTPUT=False
# ---------------------------------------------------------------------------


class TestSendThreadedOutputGate:
    @pytest.mark.unit
    async def test_returns_none_when_threaded_output_disabled(self) -> None:
        host = _ThreadedHost()
        host.THREADED_OUTPUT = False
        session = _make_session()
        result = await host.send_threaded_output(session, "hello")
        assert result is None

    @pytest.mark.unit
    async def test_threaded_output_enabled_processes_text(self, host: _ThreadedHost) -> None:
        session = _make_session()
        with patch("teleclaude.core.db.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            result = await host.send_threaded_output(session, "hello world")
        # Should return a message id (from the mocked send_message)
        assert result is not None


# ---------------------------------------------------------------------------
# Badge emission
# ---------------------------------------------------------------------------


class TestBadgeEmission:
    @pytest.mark.unit
    async def test_badge_sent_on_first_call(self, host: _ThreadedHost) -> None:
        session = _make_session()
        host._badge_sent = False
        host.client.send_message = AsyncMock(return_value="badge-msg")

        with patch("teleclaude.core.db.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await host.send_threaded_output(session, "some text")

        host.client.send_message.assert_called()
        assert host._badge_sent is True

    @pytest.mark.unit
    async def test_badge_not_sent_again_when_already_sent(self, host: _ThreadedHost) -> None:
        session = _make_session()
        host._badge_sent = True
        host.client.send_message = AsyncMock(return_value="irrelevant")

        with patch("teleclaude.core.db.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await host.send_threaded_output(session, "text")

        host.client.send_message.assert_not_called()

    @pytest.mark.unit
    async def test_discord_adapter_skips_badge(self) -> None:
        host = _ThreadedHost()
        host.ADAPTER_KEY = "discord"
        session = _make_session()
        host._badge_sent = False
        host.client.send_message = AsyncMock(return_value="irrelevant")

        with patch("teleclaude.core.db.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await host.send_threaded_output(session, "text")

        host.client.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# Char offset management
# ---------------------------------------------------------------------------


class TestCharOffsetManagement:
    @pytest.mark.unit
    async def test_offset_resets_when_text_shorter_than_offset(self, host: _ThreadedHost) -> None:
        session = _make_session()
        host._badge_sent = True
        host._char_offset = 100  # More than text length

        with patch("teleclaude.core.db.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await host.send_threaded_output(session, "short")

        assert host._char_offset == 0 or host._char_offset <= 5

    @pytest.mark.unit
    async def test_no_active_text_with_existing_message_returns_id(self, host: _ThreadedHost) -> None:
        session = _make_session()
        host._badge_sent = True
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
    @pytest.mark.unit
    async def test_long_text_triggers_pagination(self, host: _ThreadedHost) -> None:
        host.max_message_size = 20
        session = _make_session()
        host._badge_sent = True
        long_text = "a" * 100

        with patch("teleclaude.core.db.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await host.send_threaded_output(session, long_text)

        # Offset should advance past zero — pagination occurred
        assert host._char_offset > 0

    @pytest.mark.unit
    async def test_short_text_within_limit_delivered_directly(self, host: _ThreadedHost) -> None:
        session = _make_session()
        host._badge_sent = True
        short_text = "hi"

        with patch("teleclaude.core.db.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            result = await host.send_threaded_output(session, short_text)

        assert result is not None
