"""Characterization tests for teleclaude.adapters.telegram.input_handlers."""

from __future__ import annotations

from collections.abc import Mapping
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
        self._topic_ready_events: dict[int, object] = {}
        self._topic_ready_cache: set[int] = set()
        self.sent_messages: list[tuple[int | None, str, str | None, object | None]] = []

    def _metadata(self, **kwargs: object) -> MessageMetadata:
        return MessageMetadata(channel_metadata=dict(kwargs))

    async def _get_session_from_topic(self, update: object) -> None:
        return None

    async def _dispatch_command(
        self,
        session: object,
        message_id: str | None,
        metadata: MessageMetadata,
        command_name: str,
        payload: Mapping[str, object],
        handler: object,
    ) -> None:
        return None

    def _topic_owned_by_this_bot(self, update: object, topic_id: int) -> bool:
        return False

    async def _delete_orphan_topic(self, topic_id: int) -> None:
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
# IncomingFileType enum
# ---------------------------------------------------------------------------


def test_incoming_file_type_document_value():
    assert IncomingFileType.DOCUMENT.value == "document"


def test_incoming_file_type_photo_value():
    assert IncomingFileType.PHOTO.value == "photo"


# ---------------------------------------------------------------------------
# FILE_SUBDIR mapping
# ---------------------------------------------------------------------------


def test_file_subdir_document_maps_to_files():
    assert FILE_SUBDIR[IncomingFileType.DOCUMENT] == "files"


def test_file_subdir_photo_maps_to_photos():
    assert FILE_SUBDIR[IncomingFileType.PHOTO] == "photos"


def test_file_subdir_covers_all_incoming_types():
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
    msg = _make_empty_message()
    msg.text = "hello"
    result = _describe_message_content(msg)
    assert any("text" in part for part in result)


def test_describe_message_content_returns_voice_when_voice_present():
    msg = _make_empty_message()
    msg.voice = MagicMock()
    result = _describe_message_content(msg)
    assert "voice" in result


def test_describe_message_content_returns_photo_when_photo_present():
    msg = _make_empty_message()
    msg.photo = [MagicMock()]
    result = _describe_message_content(msg)
    assert "photo" in result


def test_describe_message_content_returns_document_when_document_present():
    msg = _make_empty_message()
    msg.document = MagicMock()
    result = _describe_message_content(msg)
    assert "document" in result


def test_describe_message_content_returns_empty_for_plain_message():
    msg = _make_empty_message()
    result = _describe_message_content(msg)
    assert result == []


def test_describe_message_content_returns_forum_topic_created():
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
    update = _make_empty_update()
    cb = MagicMock()
    cb.data = "test:data"
    update.callback_query = cb
    result = _describe_update_extras(update)
    assert any("callback_query" in part for part in result)


def test_describe_update_extras_returns_empty_for_plain_update():
    update = _make_empty_update()
    result = _describe_update_extras(update)
    assert result == []


def test_describe_update_extras_returns_poll_update_when_present():
    update = _make_empty_update()
    update.poll = MagicMock()
    result = _describe_update_extras(update)
    assert "poll update" in result


# ---------------------------------------------------------------------------
# _handle_help
# ---------------------------------------------------------------------------


async def test_handle_help_ignores_users_outside_whitelist():
    handler = _StubInputHandlers()
    update = MagicMock()
    update.effective_user = MagicMock(id=99)
    update.effective_message = MagicMock(message_thread_id=13)

    await handler._handle_help(update, MagicMock())

    assert handler.sent_messages == []


async def test_handle_help_sends_help_text_to_whitelisted_user():
    handler = _StubInputHandlers()
    update = MagicMock()
    update.effective_user = MagicMock(id=7)
    update.effective_message = MagicMock(message_thread_id=13)

    await handler._handle_help(update, MagicMock())

    assert len(handler.sent_messages) == 1
    message_thread_id, text, parse_mode, reply_markup = handler.sent_messages[0]
    assert message_thread_id == 13
    assert text
    assert parse_mode is None
    assert reply_markup is None
