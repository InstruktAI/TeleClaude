"""Characterization tests for teleclaude.adapters.telegram.input_handlers."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from types import SimpleNamespace
from unittest.mock import MagicMock

from teleclaude.adapters.telegram.input_handlers import (
    FILE_SUBDIR,
    IncomingFileType,
    InputHandlersMixin,
    _describe_message_content,
    _describe_update_extras,
)
from teleclaude.core.models import MessageMetadata


class _StubInputHandlers(InputHandlersMixin):
    """Minimal concrete implementation for input handler characterization."""

    def __init__(self) -> None:
        self.client = MagicMock()
        self.user_whitelist = {7}
        self._processed_voice_messages: set[str] = set()
        self._topic_ready_events: dict[int, asyncio.Event] = {}
        self._topic_ready_cache: set[int] = set()
        self.sent_messages: list[tuple[int | None, str, str | None, object | None]] = []
        self.dispatched_commands: list[tuple[object, str, MessageMetadata, str, Mapping[str, object]]] = []

    def _metadata(self, **kwargs: object) -> MessageMetadata:
        return MessageMetadata(**kwargs)

    async def _get_session_from_topic(self, _update: object) -> object | None:
        return None

    async def _dispatch_command(
        self,
        session: object,
        message_id: str,
        metadata: MessageMetadata,
        event: str,
        payload: Mapping[str, object],
        _fn: object,
    ) -> None:
        self.dispatched_commands.append((session, message_id, metadata, event, payload))

    def _topic_owned_by_this_bot(self, _update: object, _topic_id: int) -> bool:
        return False

    async def _delete_orphan_topic(self, _topic_id: int) -> None:
        return None

    async def _send_general_message_with_retry(
        self,
        message_thread_id: int | None,
        text: str,
        parse_mode: str | None,
        reply_markup: object | None,
    ) -> MagicMock:
        self.sent_messages.append((message_thread_id, text, parse_mode, reply_markup))
        return MagicMock()


# ---------------------------------------------------------------------------
# FILE_SUBDIR mapping
# ---------------------------------------------------------------------------


def test_file_subdir_covers_all_incoming_types():
    """Every supported incoming file type maps to a storage subdir."""
    for file_type in IncomingFileType:
        assert file_type in FILE_SUBDIR


# ---------------------------------------------------------------------------
# _describe_message_content
# ---------------------------------------------------------------------------


def _make_empty_message() -> MagicMock:
    msg = MagicMock()
    msg.text = None
    msg.voice = None
    msg.photo = None
    msg.document = None
    msg.forum_topic_created = None
    msg.forum_topic_closed = None
    msg.forum_topic_reopened = None
    msg.forum_topic_edited = None
    msg.delete_chat_photo = None
    msg.new_chat_members = None
    msg.left_chat_member = None
    return msg


def test_describe_message_content_returns_text_info_when_text_present():
    """Text messages report a text descriptor."""
    msg = _make_empty_message()
    msg.text = "hello"
    result = _describe_message_content(msg)
    assert any("text" in part for part in result)


def test_describe_message_content_returns_voice_when_voice_present():
    """Voice messages report the voice descriptor."""
    msg = _make_empty_message()
    msg.voice = MagicMock()
    result = _describe_message_content(msg)
    assert "voice" in result


def test_describe_message_content_returns_photo_when_photo_present():
    """Photo messages report the photo descriptor."""
    msg = _make_empty_message()
    msg.photo = [MagicMock()]
    result = _describe_message_content(msg)
    assert "photo" in result


def test_describe_message_content_returns_document_when_document_present():
    """Document messages report the document descriptor."""
    msg = _make_empty_message()
    msg.document = MagicMock()
    result = _describe_message_content(msg)
    assert "document" in result


def test_describe_message_content_returns_empty_for_plain_message():
    """Messages with no recognized payload return no descriptors."""
    msg = _make_empty_message()
    result = _describe_message_content(msg)
    assert not result


def test_describe_message_content_returns_forum_topic_created():
    """Forum topic creation events are surfaced in the descriptor list."""
    msg = _make_empty_message()
    msg.forum_topic_created = MagicMock()
    result = _describe_message_content(msg)
    assert "forum_topic_created" in result


# ---------------------------------------------------------------------------
# _describe_update_extras
# ---------------------------------------------------------------------------


def _make_empty_update() -> MagicMock:
    update = MagicMock()
    update.callback_query = None
    update.inline_query = None
    update.poll = None
    update.poll_answer = None
    update.my_chat_member = None
    update.chat_member = None
    update.chat_join_request = None
    return update


def test_describe_update_extras_returns_callback_info_when_present():
    """Callback-query updates report callback metadata in the extras list."""
    update = _make_empty_update()
    cb = MagicMock()
    cb.data = "test:data"
    update.callback_query = cb
    result = _describe_update_extras(update)
    assert any("callback_query" in part for part in result)


def test_describe_update_extras_returns_empty_for_plain_update():
    """Updates with no extra event payload return no extras."""
    update = _make_empty_update()
    result = _describe_update_extras(update)
    assert not result


def test_describe_update_extras_returns_poll_update_when_present():
    """Poll updates report the poll descriptor."""
    update = _make_empty_update()
    update.poll = MagicMock()
    result = _describe_update_extras(update)
    assert "poll update" in result


async def test_handle_text_message_dispatches_typed_actor_metadata() -> None:
    """Telegram text input must populate typed actor metadata before dispatch."""
    handler = _StubInputHandlers()
    session_id = "sess-123"
    platform_message_id = "99"
    session = SimpleNamespace(session_id=session_id)

    async def _session_from_topic(_update: object) -> object | None:
        return session

    handler._get_session_from_topic = _session_from_topic
    update = MagicMock()
    update.effective_user = MagicMock(
        id=7,
        username="telegram-user",
        full_name="Telegram User",
        first_name="Telegram",
    )
    update.effective_message = MagicMock(
        text="hello from telegram",
        message_id=int(platform_message_id),
        message_thread_id=13,
    )

    await handler._handle_text_message(update, MagicMock())

    assert len(handler.dispatched_commands) == 1
    session_arg, message_id, metadata, event, payload = handler.dispatched_commands[0]
    assert isinstance(metadata, MessageMetadata)
    assert session_arg is session
    assert message_id == platform_message_id
    assert event == "process_message"
    assert metadata.actor_id == "telegram:7"
    assert metadata.actor_name == "telegram-user"
    assert metadata.platform_message_id == platform_message_id
    assert payload == {
        "session_id": session_id,
        "text": "hello from telegram",
        "origin": "telegram",
        "actor_id": "telegram:7",
        "actor_name": "telegram-user",
        "source_message_id": platform_message_id,
    }
