"""Functional tests for Telegram manual session close interlock."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import TypedDict

import pytest

from teleclaude.adapters.telegram import private_handlers
from teleclaude.adapters.telegram.private_handlers import PrivateHandlersMixin
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.types.commands import CloseSessionCommand

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SESSION_ID = "telegram-session"
_MESSAGE_ID = 123
_EVENT_EXIT = "exit"
_EVENT_CLOSE_SESSION = "close_session"
_ORIGIN_TELEGRAM = "telegram"
_CALL_HOLD = "hold"
_CALL_CLOSE = "close"
_PAYLOAD_SESSION_ID = "session_id"
_PAYLOAD_ARGS = "args"


class _DispatchRecord(TypedDict):
    message_id: str | None
    event: str
    payload: Mapping[str, object]


class _TelegramHarness(PrivateHandlersMixin):
    SIMPLE_COMMAND_EVENTS: list[str] = []

    def __init__(self) -> None:
        self.dispatched: list[_DispatchRecord] = []
        self.session = Session(
            session_id=_SESSION_ID,
            computer_name="local",
            tmux_session_name="tmux-telegram",
            title="telegram",
        )

    async def _get_session_from_topic(self, update: object) -> Session | None:
        del update
        return self.session

    def _metadata(self) -> MessageMetadata:
        return MessageMetadata(origin=_ORIGIN_TELEGRAM)

    async def _dispatch_command(
        self,
        session: Session,
        message_id: str | None,
        metadata: MessageMetadata,
        event: str,
        payload: Mapping[str, object],
        fn: object,
    ) -> None:
        del session, metadata
        callback = fn
        if not callable(callback):
            raise AssertionError("dispatch callback must be callable")
        await callback()
        self.dispatched.append(
            {
                "message_id": message_id,
                "event": event,
                "payload": payload,
            }
        )


def _update() -> object:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(message_id=_MESSAGE_ID),
    )


def _context() -> object:
    return SimpleNamespace(args=[])


async def test_telegram_close_attempts_hold_and_continues_when_hold_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _hold(_db: object, session_id: str) -> None:
        calls.append(_CALL_HOLD)
        assert session_id == _SESSION_ID
        raise RuntimeError("hold failed")

    async def _close(command: CloseSessionCommand) -> None:
        calls.append(_CALL_CLOSE)
        assert command.session_id == _SESSION_ID

    service = SimpleNamespace(close_session=_close)
    monkeypatch.setattr(private_handlers, "hold_todo_for_manual_session_close", _hold)
    monkeypatch.setattr(private_handlers, "get_command_service", lambda: service)

    harness = _TelegramHarness()

    await harness._handle_simple_command(_update(), _context(), _EVENT_EXIT)

    assert calls == [_CALL_HOLD, _CALL_CLOSE]
    assert harness.dispatched == [
        {
            "message_id": str(_MESSAGE_ID),
            "event": _EVENT_CLOSE_SESSION,
            "payload": {_PAYLOAD_SESSION_ID: _SESSION_ID, _PAYLOAD_ARGS: []},
        }
    ]
