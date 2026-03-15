"""Characterization tests for teleclaude.adapters.ui.output_delivery."""

from __future__ import annotations

import asyncio
from hashlib import sha256
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.adapters.ui.output_delivery import OutputDeliveryMixin
from teleclaude.core.models import CleanupTrigger, MessageMetadata, Session

# ---------------------------------------------------------------------------
# Minimal concrete host that satisfies the mixin's TYPE_CHECKING contract
# ---------------------------------------------------------------------------


class _FakeHost(OutputDeliveryMixin):
    ADAPTER_KEY = "telegram"
    THREADED_OUTPUT = False
    max_message_size = 100

    def __init__(self):
        self.client = MagicMock()
        self._output_message_id: str | None = None
        self._footer_message_id: str | None = None
        self._last_edit_result = True
        self.send_message = AsyncMock(return_value="msg-new")
        self.edit_message = AsyncMock(return_value=True)
        self.delete_message = AsyncMock(return_value=True)
        self._output_delivery_locks: dict[str, asyncio.Lock] = {}

    @classmethod
    def _get_output_delivery_lock(cls, session_id: str) -> asyncio.Lock:
        return asyncio.Lock()

    async def _get_output_message_id(self, session: Session) -> str | None:
        return self._output_message_id

    async def _store_output_message_id(self, session: Session, message_id: str) -> None:
        self._output_message_id = message_id

    async def _clear_output_message_id(self, session: Session) -> None:
        self._output_message_id = None

    async def _get_footer_message_id(self, session: Session) -> str | None:
        return self._footer_message_id

    async def _store_footer_message_id(self, session: Session, message_id: str) -> None:
        self._footer_message_id = message_id

    async def _clear_footer_message_id(self, session: Session) -> None:
        self._footer_message_id = None

    async def _cleanup_footer_if_present(self, session: Session) -> None:
        self._footer_message_id = None

    def _convert_markdown_for_platform(self, text: str) -> str:
        return text

    def _fit_output_to_limit(self, tmux_output: str) -> str:
        return self.format_output(tmux_output)

    def _build_session_id_lines(self, session: Session) -> str:
        return f"📋 tc: {session.session_id}"

    def _metadata(self) -> MessageMetadata:
        return MessageMetadata()


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
# _build_output_metadata and _build_footer_metadata defaults
# ---------------------------------------------------------------------------


class TestBuildMetadataDefaults:
    @pytest.mark.unit
    def test_output_metadata_returns_message_metadata(self, host: _FakeHost) -> None:
        session = _make_session()
        result = host._build_output_metadata(session, False)
        assert isinstance(result, MessageMetadata)

    @pytest.mark.unit
    def test_footer_metadata_returns_message_metadata(self, host: _FakeHost) -> None:
        session = _make_session()
        result = host._build_footer_metadata(session)
        assert isinstance(result, MessageMetadata)

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
        host.edit_message = AsyncMock(return_value=True)
        result = await host._try_edit_output_message(session, "text", MessageMetadata())
        assert result is True

    @pytest.mark.unit
    async def test_failed_edit_clears_message_id(self, host: _FakeHost) -> None:
        session = _make_session()
        host._output_message_id = "msg-1"
        host.edit_message = AsyncMock(return_value=False)
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
        send_message = cast(AsyncMock, host.send_message)

        result = await host._deliver_output_unlocked(session, text, MessageMetadata())
        assert result == "existing-msg"
        send_message.assert_not_called()

    @pytest.mark.unit
    async def test_edit_success_returns_existing_message_id(self, host: _FakeHost) -> None:
        session = _make_session()
        session.last_output_digest = None
        host._output_message_id = "msg-existing"
        host.edit_message = AsyncMock(return_value=True)

        with patch("teleclaude.core.db.db") as mock_db:
            mock_db.update_session = AsyncMock()
            result = await host._deliver_output_unlocked(session, "new content", MessageMetadata())

        assert result == "msg-existing"

    @pytest.mark.unit
    async def test_no_existing_message_sends_new(self, host: _FakeHost) -> None:
        session = _make_session()
        session.last_output_digest = None
        host._output_message_id = None
        host.send_message = AsyncMock(return_value="msg-new")

        with patch("teleclaude.core.db.db") as mock_db:
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
        host.client.send_message = AsyncMock(return_value="msg-err")

        with patch("teleclaude.core.db.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            await host.send_error_feedback(session.session_id, "something failed")

        host.client.send_message.assert_awaited_once()
        delivered_session, delivered_text = host.client.send_message.await_args.args
        assert delivered_session is session
        assert isinstance(delivered_text, str)
        assert host.client.send_message.await_args.kwargs["cleanup_trigger"] is CleanupTrigger.NEXT_NOTICE

    @pytest.mark.unit
    async def test_missing_session_does_not_raise(self, host: _FakeHost) -> None:
        with patch("teleclaude.core.db.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            # Should not raise
            await host.send_error_feedback("nonexistent-sess", "error")


# ---------------------------------------------------------------------------
# _send_footer
# ---------------------------------------------------------------------------


class TestSendFooter:
    @pytest.mark.unit
    async def test_threaded_output_suppresses_footer(self, host: _FakeHost) -> None:
        host.THREADED_OUTPUT = True
        session = _make_session()
        result = await host._send_footer(session)
        assert result is None

    @pytest.mark.unit
    async def test_new_footer_stored_on_send(self, host: _FakeHost) -> None:
        session = _make_session()
        host._footer_message_id = None
        host.send_message = AsyncMock(return_value="footer-msg")
        result = await host._send_footer(session)
        assert result == "footer-msg"
        assert host._footer_message_id == "footer-msg"

    @pytest.mark.unit
    async def test_existing_footer_edited_not_replaced(self, host: _FakeHost) -> None:
        session = _make_session()
        host._footer_message_id = "existing-footer"
        host.edit_message = AsyncMock(return_value=True)
        send_message = cast(AsyncMock, host.send_message)
        result = await host._send_footer(session)
        assert result == "existing-footer"
        send_message.assert_not_called()

    @pytest.mark.unit
    async def test_stale_footer_edit_failure_clears_id(self, host: _FakeHost) -> None:
        session = _make_session()
        host._footer_message_id = "stale-footer"
        host.edit_message = AsyncMock(return_value=False)
        result = await host._send_footer(session)
        assert result is None
        assert host._footer_message_id is None


# ---------------------------------------------------------------------------
# Public boundary: send_output_update
# ---------------------------------------------------------------------------


class TestSendOutputUpdate:
    @pytest.mark.unit
    async def test_threaded_output_suppresses_standard_send(self, host: _FakeHost) -> None:
        host.THREADED_OUTPUT = True
        session = _make_session()
        result = await host.send_output_update(session, "output", 0.0, 0.0)
        assert result is None

    @pytest.mark.unit
    async def test_final_output_delegates_to_deliver_output(self, host: _FakeHost) -> None:
        session = _make_session()
        with (
            patch("teleclaude.adapters.ui.output_delivery.config") as mock_cfg,
            patch.object(host, "_fit_output_to_limit", return_value="formatted-output") as fit_output,
            patch.object(host, "_deliver_output", new=AsyncMock(return_value="msg-final")) as deliver_output,
        ):
            mock_cfg.terminal.strip_ansi = False
            mock_cfg.computer.timezone = "UTC"
            result = await host.send_output_update(session, "output", 0.0, 0.0, is_final=True, exit_code=0)
        assert result == "msg-final"
        fit_output.assert_called_once_with("output")
        delivered_session, delivered_text, delivered_metadata = deliver_output.await_args.args
        assert delivered_session is session
        assert delivered_text == "formatted-output"
        assert isinstance(delivered_metadata, MessageMetadata)
        assert bool(deliver_output.await_args.kwargs["status_line"])

    @pytest.mark.unit
    async def test_active_output_delegates_to_deliver_output(self, host: _FakeHost) -> None:
        session = _make_session()
        with (
            patch("teleclaude.adapters.ui.output_delivery.config") as mock_cfg,
            patch.object(host, "_fit_output_to_limit", return_value="formatted-output") as fit_output,
            patch.object(host, "_deliver_output", new=AsyncMock(return_value="msg-active")) as deliver_output,
        ):
            mock_cfg.terminal.strip_ansi = False
            mock_cfg.computer.timezone = "UTC"
            result = await host.send_output_update(session, "output", 0.0, 0.0, is_final=False)
        assert result == "msg-active"
        fit_output.assert_called_once_with("output")
        delivered_session, delivered_text, delivered_metadata = deliver_output.await_args.args
        assert delivered_session is session
        assert delivered_text == "formatted-output"
        assert isinstance(delivered_metadata, MessageMetadata)
        assert bool(deliver_output.await_args.kwargs["status_line"])
