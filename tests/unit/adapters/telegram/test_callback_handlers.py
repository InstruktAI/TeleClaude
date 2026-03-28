"""Characterization tests for teleclaude.adapters.telegram.callback_handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from teleclaude.adapters.telegram.callback_handlers import (
    CallbackHandlersMixin,
)
from teleclaude.core.models import MessageMetadata


class _StubCallbackHandlers(CallbackHandlersMixin):
    """Stub that records dispatched sub-handler calls for dispatch characterization tests."""

    def __init__(self) -> None:
        self.client = MagicMock()
        self.trusted_dirs: list[object] = []  # pyright: ignore[reportIncompatibleVariableOverride]
        self.user_whitelist: set[int] = set()
        self.computer_name = "test-computer"
        self.calls: list[tuple[str, object, object]] = []

    @property
    def bot(self) -> MagicMock:
        return MagicMock()

    def _build_project_keyboard(self, callback_prefix: str) -> MagicMock:
        return MagicMock()

    def _build_heartbeat_keyboard(self, bot_username: str) -> MagicMock:
        return MagicMock()

    async def _send_document_with_retry(
        self,
        chat_id: int,
        message_thread_id: int,
        file_path: str,
        filename: str,
        caption: str | None = None,
    ) -> MagicMock:
        return MagicMock()

    def _metadata(self, **kwargs: object) -> MessageMetadata:
        return MessageMetadata(channel_metadata=dict(kwargs))

    async def _handle_download_full(self, query: object, args: list[str]) -> None:
        self.calls.append(("download_full", query, args))

    async def _handle_session_select(self, query: object) -> None:
        self.calls.append(("session_select", query, None))

    async def _handle_agent_select(self, query: object, agent_name: str, *, is_resume: bool) -> None:
        self.calls.append(("agent_select", query, (agent_name, is_resume)))

    async def _handle_cancel(self, query: object, args: list[str]) -> None:
        self.calls.append(("cancel", query, args))

    async def _handle_session_start(self, query: object, args: list[str]) -> None:
        self.calls.append(("session_start", query, args))

    async def _handle_agent_start(
        self,
        query: object,
        agent_name: str,
        *,
        is_resume: bool,
        args: list[str],
    ) -> None:
        self.calls.append(("agent_start", query, (agent_name, is_resume, args)))


# ---------------------------------------------------------------------------
# _handle_callback_query — dispatch boundary
# ---------------------------------------------------------------------------


async def test_handle_callback_query_is_noop_when_callback_query_is_none():
    handler = _StubCallbackHandlers()
    update = MagicMock()
    update.callback_query = None
    await handler._handle_callback_query(update, MagicMock())
    assert handler.calls == []


async def test_handle_callback_query_is_noop_when_data_has_no_separator():
    handler = _StubCallbackHandlers()
    query = MagicMock()
    query.data = "noseparator"
    query.answer = AsyncMock()
    update = MagicMock(callback_query=query)
    await handler._handle_callback_query(update, MagicMock())
    assert handler.calls == []


async def test_handle_callback_query_ignores_unknown_action():
    handler = _StubCallbackHandlers()
    query = MagicMock()
    query.data = "unknownaction:arg"
    query.answer = AsyncMock()
    update = MagicMock(callback_query=query)
    await handler._handle_callback_query(update, MagicMock())
    assert handler.calls == []


async def test_handle_callback_query_routes_session_select_action():
    handler = _StubCallbackHandlers()
    query = MagicMock()
    query.answer = AsyncMock()
    query.data = "ssel:ignored"
    update = MagicMock(callback_query=query)

    await handler._handle_callback_query(update, MagicMock())

    query.answer.assert_awaited_once()
    assert handler.calls == [("session_select", query, None)]


async def test_handle_callback_query_routes_asel_with_agent_name():
    handler = _StubCallbackHandlers()
    query = MagicMock()
    query.answer = AsyncMock()
    query.data = "asel:claude"
    update = MagicMock(callback_query=query)

    await handler._handle_callback_query(update, MagicMock())

    assert handler.calls == [("agent_select", query, ("claude", False))]


async def test_handle_callback_query_routes_legacy_resume_select_to_gemini():
    """Legacy grsel payload is rewritten to arsel:gemini and dispatched as resume=True."""
    handler = _StubCallbackHandlers()
    query = MagicMock()
    query.answer = AsyncMock()
    query.data = "grsel:bot-user"
    update = MagicMock(callback_query=query)

    await handler._handle_callback_query(update, MagicMock())

    assert handler.calls == [("agent_select", query, ("gemini", True))]


async def test_handle_callback_query_routes_legacy_select_to_codex():
    """Legacy cxsel payload is rewritten to asel:codex and dispatched as resume=False."""
    handler = _StubCallbackHandlers()
    query = MagicMock()
    query.answer = AsyncMock()
    query.data = "cxsel:bot-user"
    update = MagicMock(callback_query=query)

    await handler._handle_callback_query(update, MagicMock())

    assert handler.calls == [("agent_select", query, ("codex", False))]


async def test_handle_callback_query_routes_legacy_resume_start_to_codex():
    """Legacy cxr payload is rewritten to ars:codex and dispatched as resume=True."""
    handler = _StubCallbackHandlers()
    query = MagicMock()
    query.answer = AsyncMock()
    query.data = "cxr:bot-user:native-42"
    update = MagicMock(callback_query=query)

    await handler._handle_callback_query(update, MagicMock())

    assert handler.calls == [("agent_start", query, ("codex", True, ["bot-user", "native-42"]))]
