"""Characterization tests for teleclaude.adapters.telegram.callback_handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from teleclaude.adapters.telegram.callback_handlers import CallbackHandlersMixin


class _StubCallbackHandlers(CallbackHandlersMixin):
    """Stub that records dispatched sub-handler calls for dispatch characterization tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object]] = []

    async def _handle_download_full(self, query: object, args: list[str]) -> None:
        self.calls.append(("download_full", query, args))

    async def handle_callback_query(self, update: object, context: object) -> None:
        """Expose the mixin boundary without calling a protected method from tests."""
        await self._handle_callback_query(update, context)


async def test_handle_callback_query_is_noop_when_callback_query_is_none():
    """Missing callback queries are ignored."""
    handler = _StubCallbackHandlers()
    update = MagicMock()
    update.callback_query = None
    await handler.handle_callback_query(update, MagicMock())
    assert not handler.calls


async def test_handle_callback_query_is_noop_when_data_has_no_separator():
    """Malformed callback payloads are ignored."""
    handler = _StubCallbackHandlers()
    query = MagicMock()
    query.data = "noseparator"
    query.answer = AsyncMock()
    update = MagicMock(callback_query=query)
    await handler.handle_callback_query(update, MagicMock())
    assert not handler.calls


async def test_handle_callback_query_ignores_unknown_action():
    """Unknown callback actions are ignored."""
    handler = _StubCallbackHandlers()
    query = MagicMock()
    query.data = "unknownaction:arg"
    query.answer = AsyncMock()
    update = MagicMock(callback_query=query)
    await handler.handle_callback_query(update, MagicMock())
    assert not handler.calls


async def test_handle_callback_query_routes_download_full_to_handler():
    """download_full payloads dispatch to the transcript-download handler."""
    handler = _StubCallbackHandlers()
    query = MagicMock()
    query.answer = AsyncMock()
    query.data = "download_full:sess-42"
    update = MagicMock(callback_query=query)

    await handler.handle_callback_query(update, MagicMock())

    query.answer.assert_awaited_once()
    assert handler.calls == [("download_full", query, ["sess-42"])]
