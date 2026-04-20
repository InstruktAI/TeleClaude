"""Characterization tests for output delivery on UiAdapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from hashlib import sha256
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.models import ChannelMetadata, MessageMetadata, PeerInfo, Session

# ---------------------------------------------------------------------------
# Minimal concrete host that satisfies UiAdapter's abstract methods
# ---------------------------------------------------------------------------


class _FakeHost(UiAdapter):
    ADAPTER_KEY = "telegram"
    max_message_size = 100
    OUTPUT_CADENCE_SECONDS = 0.0

    def __init__(self):
        # Skip UiAdapter.__init__ to avoid event_bus side effects
        self.client = MagicMock()
        self._output_message_id: str | None = None
        self._last_edit_result = True
        self._output_delivery_locks: dict[str, asyncio.Lock] = {}
        self._output_cadence = None

        # Mocked methods — assigned as instance attrs
        self._send_message_mock = AsyncMock(return_value="msg-new")
        self._edit_message_mock = AsyncMock(return_value=True)
        self._delete_message_mock = AsyncMock(return_value=True)

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
        return await self._delete_message_mock(session, message_id)

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

    async def _get_output_message_id(self, _session: Session) -> str | None:
        return self._output_message_id

    async def _store_output_message_id(self, _session: Session, message_id: str) -> None:
        self._output_message_id = message_id

    async def _clear_output_message_id(self, _session: Session) -> None:
        self._output_message_id = None


def _make_session(**kwargs: object) -> Session:
    return Session(
        session_id="sess-abc",
        computer_name="local",
        tmux_session_name="test",
        title="Test",
        **kwargs,
    )


@pytest.fixture
def host() -> _FakeHost:
    return _FakeHost()


# ---------------------------------------------------------------------------
# _build_metadata_for_thread
# ---------------------------------------------------------------------------


class TestBuildMetadataDefaults:
    @pytest.mark.unit
    def test_build_metadata_for_thread_returns_message_metadata(self, host: _FakeHost) -> None:
        result = host._build_metadata_for_thread()
        assert isinstance(result, MessageMetadata)


# ---------------------------------------------------------------------------
# _try_edit_output_message
# ---------------------------------------------------------------------------


class TestTryEditOutputMessage:
    @pytest.mark.unit
    async def test_no_message_id_returns_false(self, host: _FakeHost) -> None:
        session = _make_session()
        host._output_message_id = None
        result = await host._try_edit_output_message(session, "text", MessageMetadata())
        assert result is False

    @pytest.mark.unit
    async def test_successful_edit_returns_true(self, host: _FakeHost) -> None:
        session = _make_session()
        host._output_message_id = "msg-1"
        host._edit_message_mock = AsyncMock(return_value=True)
        result = await host._try_edit_output_message(session, "text", MessageMetadata())
        assert result is True

    @pytest.mark.unit
    async def test_failed_edit_clears_message_id(self, host: _FakeHost) -> None:
        session = _make_session()
        host._output_message_id = "msg-1"
        host._edit_message_mock = AsyncMock(return_value=False)
        result = await host._try_edit_output_message(session, "text", MessageMetadata())
        assert result is False
        assert host._output_message_id is None


# ---------------------------------------------------------------------------
# _deliver_output_unlocked (dedup and send/edit path)
# ---------------------------------------------------------------------------


class TestDeliverOutputUnlocked:
    @pytest.mark.unit
    async def test_same_digest_skips_delivery_and_returns_existing_id(self, host: _FakeHost) -> None:
        session = _make_session()
        text = "same content"
        digest = sha256(text.encode()).hexdigest()
        session.last_output_digest = digest
        host._output_message_id = "existing-msg"

        result = await host._deliver_output_unlocked(session, text, MessageMetadata())
        assert result == "existing-msg"
        host._send_message_mock.assert_not_called()

    @pytest.mark.unit
    async def test_edit_success_returns_existing_message_id(self, host: _FakeHost) -> None:
        session = _make_session()
        session.last_output_digest = None
        host._output_message_id = "msg-existing"
        host._edit_message_mock = AsyncMock(return_value=True)

        with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
            mock_db.update_session = AsyncMock()
            result = await host._deliver_output_unlocked(session, "new content", MessageMetadata())

        assert result == "msg-existing"

    @pytest.mark.unit
    async def test_no_existing_message_sends_new(self, host: _FakeHost) -> None:
        session = _make_session()
        session.last_output_digest = None
        host._output_message_id = None
        host._send_message_mock = AsyncMock(return_value="msg-new")

        with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
            mock_db.update_session = AsyncMock()
            result = await host._deliver_output_unlocked(session, "text", MessageMetadata())

        assert result == "msg-new"
        assert host._output_message_id == "msg-new"


# ---------------------------------------------------------------------------
# send_error_feedback
# ---------------------------------------------------------------------------


class TestSendErrorFeedback:
    @pytest.mark.unit
    async def test_sends_feedback_message_when_session_exists(self, host: _FakeHost) -> None:
        session = _make_session()
        host._send_message_mock = AsyncMock(return_value="msg-err")

        with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            await host.send_error_feedback(session.session_id, "something failed")

        host._send_message_mock.assert_awaited_once()

    @pytest.mark.unit
    async def test_missing_session_does_not_raise(self, host: _FakeHost) -> None:
        with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            # Should not raise
            await host.send_error_feedback("nonexistent-sess", "error")
