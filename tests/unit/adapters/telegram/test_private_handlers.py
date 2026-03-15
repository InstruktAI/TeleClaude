"""Characterization tests for teleclaude.adapters.telegram.private_handlers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from teleclaude.adapters.telegram.private_handlers import PrivateHandlersMixin
from teleclaude.core.models import MessageMetadata, Session, SessionAdapterMetadata, TelegramAdapterMetadata
from teleclaude.types.commands import KeysCommand


class _StubPrivateHandlers(PrivateHandlersMixin):
    """Minimal concrete implementation for testing PrivateHandlersMixin."""

    SIMPLE_COMMAND_EVENTS: list[str] = ["cancel2x", "kill", "tab"]

    def __init__(self) -> None:
        self._dispatch_calls: list[tuple[object, ...]] = []

    def _metadata(self, **_kwargs: object) -> MessageMetadata:
        return MessageMetadata()

    async def _get_session_from_topic(self, update: object) -> None:
        return None

    async def _dispatch_command(
        self,
        session: object,
        message_id: object,
        metadata: object,
        event: object,
        payload: object,
        fn: object,
    ) -> None:
        self._dispatch_calls.append((session, message_id, metadata, event, payload, fn))


def _make_session(session_id: str = "sess-1", user_id: int | None = None) -> Session:
    return Session(
        session_id=session_id,
        computer_name="test-computer",
        tmux_session_name=f"tmux-{session_id}",
        title="Test Session",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(user_id=user_id)),
    )


# ---------------------------------------------------------------------------
# _register_simple_command_handlers
# ---------------------------------------------------------------------------


def test_register_simple_command_handlers_creates_handler_for_each_event():
    stub = _StubPrivateHandlers()
    stub._register_simple_command_handlers()
    for event in stub.SIMPLE_COMMAND_EVENTS:
        handler_name = f"_handle_{event}"
        assert hasattr(stub, handler_name), f"Missing handler: {handler_name}"


def test_register_simple_command_handlers_creates_callables():
    stub = _StubPrivateHandlers()
    stub._register_simple_command_handlers()
    for event in stub.SIMPLE_COMMAND_EVENTS:
        handler_name = f"_handle_{event}"
        assert callable(getattr(stub, handler_name))


def test_register_simple_command_handlers_skips_already_defined():
    """Handler defined before registration must not be overwritten."""
    stub = _StubPrivateHandlers()
    original = object()
    stub._handle_kill = original
    stub._register_simple_command_handlers()
    assert stub._handle_kill is original


# ---------------------------------------------------------------------------
# _handle_cancel_command
# ---------------------------------------------------------------------------


async def test_handle_cancel_command_calls_simple_command_with_cancel():
    stub = _StubPrivateHandlers()
    update = MagicMock()
    context = MagicMock()
    called_events: list[str] = []

    async def _capture_simple(_upd: object, _ctx: object, evt: str) -> None:
        called_events.append(evt)

    stub._handle_simple_command = _capture_simple
    await stub._handle_cancel_command(update, context)
    assert called_events == ["cancel"]


# ---------------------------------------------------------------------------
# private chat routing
# ---------------------------------------------------------------------------


async def test_handle_private_start_replies_when_invite_token_is_missing():
    stub = _StubPrivateHandlers()
    update = MagicMock()
    update.effective_user = MagicMock(id=77, username="tester", first_name="Test")
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock(args=[])

    await stub._handle_private_start(update, context)

    update.effective_message.reply_text.assert_awaited_once()


async def test_handle_private_text_processes_message_for_existing_private_session():
    stub = _StubPrivateHandlers()
    update = MagicMock()
    update.effective_user = MagicMock(id=77)
    update.effective_message = MagicMock(message_id=123, text="hello")
    context = MagicMock()
    session = _make_session(user_id=77)
    identity = SimpleNamespace(person_name="Alice", person_role="member")
    command_service = MagicMock()
    command_service.process_message = AsyncMock()

    with (
        patch("teleclaude.core.identity.get_identity_resolver") as mock_resolver,
        patch("teleclaude.adapters.telegram.private_handlers.db") as mock_db,
        patch("teleclaude.core.command_registry.get_command_service", return_value=command_service),
    ):
        mock_resolver.return_value.resolve.return_value = identity
        mock_db.list_sessions = AsyncMock(return_value=[session])

        await stub._handle_private_text(update, context)

    command_service.process_message.assert_awaited_once()
    command = command_service.process_message.await_args.args[0]
    assert command.session_id == session.session_id
    assert command.actor_name == "Alice"
    assert command.source_message_id == "123"


async def test_handle_simple_command_dispatches_keys_command_payload():
    stub = _StubPrivateHandlers()
    session = _make_session()
    stub._get_session_from_topic = AsyncMock(return_value=session)
    update = MagicMock()
    update.effective_user = MagicMock(id=7)
    update.effective_message = MagicMock(message_id=42)
    context = MagicMock(args=["shift"])
    command_service = MagicMock()
    command_service.keys = AsyncMock()
    mapped = KeysCommand(session_id=session.session_id, key="tab", args=["shift"])

    with (
        patch("teleclaude.adapters.telegram.private_handlers.CommandMapper.map_telegram_input", return_value=mapped),
        patch("teleclaude.adapters.telegram.private_handlers.get_command_service", return_value=command_service),
    ):
        await stub._handle_simple_command(update, context, "tab")

    assert len(stub._dispatch_calls) == 1
    dispatched = stub._dispatch_calls[0]
    assert dispatched[0] == session
    assert dispatched[1] == "42"
    assert dispatched[3] == "tab"
    assert dispatched[4] == {"session_id": session.session_id, "args": ["shift"]}


# ---------------------------------------------------------------------------
# delete_message — string session_id path
# ---------------------------------------------------------------------------


async def test_delete_message_with_string_session_id_returns_false_when_not_found():
    stub = _StubPrivateHandlers()
    with patch("teleclaude.adapters.telegram.private_handlers.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=None)
        result = await stub.delete_message("nonexistent-session-id", "42")
    assert result is False


async def test_delete_message_with_session_object_delegates_to_message_ops():
    stub = _StubPrivateHandlers()
    session_obj = MagicMock()
    session_obj.session_id = "sess-1"

    with patch(
        "teleclaude.adapters.telegram.message_ops.MessageOperationsMixin.delete_message",
        new_callable=AsyncMock,
    ) as mock_delete:
        mock_delete.return_value = True
        result = await stub.delete_message(session_obj, "99")

    mock_delete.assert_called_once()
    assert result is True
