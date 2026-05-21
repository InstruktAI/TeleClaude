"""Characterization tests for threaded output delivery on UiAdapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.models import ChannelMetadata, MessageMetadata, PeerInfo, Session
from teleclaude.utils.markdown import (
    GFM_MARKDOWN_INITIAL_STATE,
    GfmMarkdownState,
    continuation_prefix_for_gfm_state,
    scan_gfm_state,
    truncate_gfm_with_consumed,
)

# ---------------------------------------------------------------------------
# Minimal concrete host for testing
# ---------------------------------------------------------------------------


class _ThreadedHost(UiAdapter):
    ADAPTER_KEY = "telegram"
    max_message_size = 50
    THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS = 50
    OUTPUT_CADENCE_SECONDS = 0.0

    def __init__(self) -> None:
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

    async def update_channel_title(self, session: Session) -> bool:
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
        yield

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

    async def _deliver_output_unlocked(
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
    async def test_offset_resets_when_text_shorter_than_offset(self, host: _ThreadedHost) -> None:
        """Offset resets to zero when text is shorter than the recorded offset."""
        session = _make_session()
        host._char_offset = 100  # More than text length

        with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await host.send_threaded_output(session, "short")

        assert host._char_offset == 0 or host._char_offset <= 5

    @pytest.mark.unit
    async def test_no_active_text_with_existing_message_returns_id(self, host: _ThreadedHost) -> None:
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
    async def test_long_text_triggers_pagination(self, host: _ThreadedHost) -> None:
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
    async def test_short_text_within_limit_delivered_directly(self, host: _ThreadedHost) -> None:
        """Short text within the size limit is delivered without pagination."""
        session = _make_session()
        short_text = "hi"

        with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            result = await host.send_threaded_output(session, short_text)

        assert result is not None

    @pytest.mark.unit
    async def test_overflow_message_splits_without_thread_state(self, host: _ThreadedHost) -> None:
        """Standalone UI messages reuse overflow splitting without touching threaded output state."""
        host.max_message_size = 20
        session = _make_session()
        long_text = "alpha " * 20

        result = await host.send_overflow_message(session, long_text, metadata=MessageMetadata())

        assert len(result) > 1
        assert host._char_offset == 0
        assert host._output_message_id is None
        sent_chunks = [call.args[1] for call in host._send_message_mock.await_args_list]
        assert len(sent_chunks) == len(result)
        assert all(len(chunk) <= host.max_message_size for chunk in sent_chunks)


# ---------------------------------------------------------------------------
# Marker bookkeeping across chunk boundaries (regression)
# ---------------------------------------------------------------------------


class _GfmHost(_ThreadedHost):
    """Host configured with the GFM markdown strategy (Discord dialect)."""

    max_message_size = 60  # tiny limit to force overflow on short fixtures

    def __init__(self) -> None:
        super().__init__()
        # Record every display_text that reaches the live-delivery path so the
        # tests can inspect the rendered body for marker correctness.
        self.delivered_bodies: list[str] = []

    def _markdown_initial_state(self) -> object:
        return GFM_MARKDOWN_INITIAL_STATE

    def _continuation_prefix_for_state(self, state: object) -> str:
        return continuation_prefix_for_gfm_state(cast(GfmMarkdownState, state))

    def _truncate_for_overflow(self, body_text: str, max_chars: int) -> tuple[str, int]:
        return truncate_gfm_with_consumed(body_text, max_chars=max_chars, suffix="")

    def _scan_markdown_state(self, consumed: str, state: object) -> object:
        return scan_gfm_state(consumed, initial_state=cast(GfmMarkdownState, state))

    async def _deliver_output_unlocked(
        self,
        session: Session,
        text: str,
        metadata: MessageMetadata,
        **delivery_kwargs: object,
    ) -> str | None:
        self.delivered_bodies.append(text)
        if self._output_message_id:
            return self._output_message_id
        new_id = await self.send_message(session, text, metadata=metadata)
        if new_id:
            self._output_message_id = new_id
        return new_id


class TestMarkerBookkeepingAcrossRenders:
    """Regression: re-derive open-marker state from text[:char_offset] every render.

    The bug: a per-call ``_continuation_state`` parameter was the only carrier of
    "what markers are open at the resume point". On the immediate post-overflow
    recursive call it survived; on the *next* top-level render it was reset to
    the initial state, so the post-seal chunk B was edited with content that
    dropped the reopened code-fence prefix. Subsequent edits buried the fence
    and Discord/Telegram showed unfenced content where a fenced block was
    intended.

    These tests pin the stateless behaviour: every render scans
    ``text[:char_offset]`` and re-derives the prefix.
    """

    @pytest.mark.unit
    async def test_post_seal_chunk_keeps_reopen_prefix_on_next_render(self) -> None:
        """Render N+1 must edit chunk B *with* the reopened code-fence prefix."""
        host = _GfmHost()
        session = _make_session()

        # Long text with an unclosed code fence that overflows the 60-char limit.
        # Chunk A will be sealed with a closing fence; chunk B is the remainder
        # and must keep the ```\n reopen prefix on every subsequent edit.
        long_text = "Here is code:\n```python\n" + ("print('x')\n" * 8) + "```\nDone."

        with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            mock_db.update_origin_metadata = AsyncMock()
            mock_db.update_session = AsyncMock()

            # ----- Render N: triggers overflow + recursive seal+continue -----
            await host.send_threaded_output(session, long_text)

        # Char offset advanced past chunk A and chunk B is the new active region.
        offset_after_n = host._char_offset
        assert offset_after_n > 0
        assert offset_after_n < len(long_text)
        assert host._output_message_id is not None  # chunk B id stored

        # State at the resume point must include the open code fence so the
        # reopen prefix is reapplied on chunk B.
        derived_state = scan_gfm_state(long_text[:offset_after_n])
        derived_prefix = continuation_prefix_for_gfm_state(derived_state)
        assert derived_prefix == "```\n", f"Expected open code fence at offset {offset_after_n}, got {derived_prefix!r}"

        # The chunk-B body delivered during render N must already include the
        # reopen prefix (proves the recursive call wired it correctly).
        bodies_after_n = list(host.delivered_bodies)
        assert bodies_after_n, "expected at least one delivered body during render N"
        chunk_b_first_body = bodies_after_n[-1]
        assert chunk_b_first_body.startswith("```\n"), (
            f"chunk B first delivery missing reopen prefix: {chunk_b_first_body!r}"
        )

        # ----- Render N+1: NEW top-level call, extended text -----
        # This is the regression case: previously _continuation_state defaulted
        # to initial here and the rendered body went out without the reopen prefix.
        host.delivered_bodies.clear()

        extended_text = long_text + " more text"
        with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            mock_db.update_origin_metadata = AsyncMock()
            mock_db.update_session = AsyncMock()

            await host.send_threaded_output(session, extended_text)

        # The body delivered on render N+1 must carry the reopen prefix.
        bodies_after_next = list(host.delivered_bodies)
        assert bodies_after_next, "expected at least one delivered body during render N+1"
        next_body = bodies_after_next[-1]
        assert next_body.startswith("```\n"), f"render N+1 dropped reopen prefix — bug regressed. Got: {next_body!r}"
