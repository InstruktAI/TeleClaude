"""Characterization tests for teleclaude.adapters.telegram.message_ops."""

from __future__ import annotations

from dataclasses import is_dataclass
from unittest.mock import AsyncMock, MagicMock

from teleclaude.adapters.telegram.message_ops import EditContext, MessageOperationsMixin
from teleclaude.core.models import MessageMetadata, Session, SessionAdapterMetadata, TelegramAdapterMetadata


class _StubMessageOps(MessageOperationsMixin):
    """Minimal concrete implementation for testing MessageOperationsMixin."""

    def __init__(self) -> None:
        self._pending_edits: dict[str, EditContext] = {}
        self._last_edit_hash: dict[str, str] = {}
        self.supergroup_id = 12345
        self._bot = MagicMock()
        self._bot.send_message = AsyncMock(return_value=MagicMock(message_id=101))
        self._bot.edit_message_text = AsyncMock()
        self.waited_for_topic: list[tuple[int, str]] = []

    @property
    def bot(self):
        return self._bot

    def _ensure_started(self) -> None:
        pass

    async def _wait_for_topic_ready(self, topic_id: int, title: str) -> None:
        self.waited_for_topic.append((topic_id, title))


def _make_session(session_id: str = "sess-1", topic_id: int | None = 7) -> Session:
    return Session(
        session_id=session_id,
        computer_name="test-computer",
        tmux_session_name=f"tmux-{session_id}",
        title="Test Session",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=topic_id)),
    )


# ---------------------------------------------------------------------------
# EditContext dataclass
# ---------------------------------------------------------------------------


def test_edit_context_is_a_dataclass():
    assert is_dataclass(EditContext)


def test_edit_context_stores_message_id_and_text():
    ctx = EditContext(message_id="42", text="hello")
    assert ctx.message_id == "42"
    assert ctx.text == "hello"


def test_edit_context_defaults_reply_markup_and_parse_mode_to_none():
    ctx = EditContext(message_id="1", text="x")
    assert ctx.reply_markup is None
    assert ctx.parse_mode is None


def test_edit_context_supports_in_place_mutation():
    ctx = EditContext(message_id="1", text="original")
    ctx.text = "updated"
    assert ctx.text == "updated"


# ---------------------------------------------------------------------------
# _content_hash
# ---------------------------------------------------------------------------


def test_content_hash_is_deterministic():
    h1 = MessageOperationsMixin._content_hash("hello", "MarkdownV2", None)
    h2 = MessageOperationsMixin._content_hash("hello", "MarkdownV2", None)
    assert h1 == h2


def test_content_hash_differs_for_different_text():
    h1 = MessageOperationsMixin._content_hash("hello", None, None)
    h2 = MessageOperationsMixin._content_hash("world", None, None)
    assert h1 != h2


def test_content_hash_differs_for_different_parse_mode():
    h1 = MessageOperationsMixin._content_hash("hello", "MarkdownV2", None)
    h2 = MessageOperationsMixin._content_hash("hello", None, None)
    assert h1 != h2


def test_content_hash_is_valid_hex_string():
    h = MessageOperationsMixin._content_hash("text", None, None)
    int(h, 16)  # raises ValueError if not valid hex


# ---------------------------------------------------------------------------
# _truncate_for_platform
# ---------------------------------------------------------------------------


def test_truncate_for_platform_returns_text_unchanged_when_within_limit():
    ops = _StubMessageOps()
    result = ops._truncate_for_platform("short text", None, 100)
    assert result == "short text"


def test_truncate_for_platform_truncates_plain_text_to_max_chars():
    ops = _StubMessageOps()
    result = ops._truncate_for_platform("abcdef", None, 3)
    assert result == "abc"


def test_truncate_for_platform_does_not_truncate_at_exact_boundary():
    ops = _StubMessageOps()
    result = ops._truncate_for_platform("abc", None, 3)
    assert result == "abc"


def test_truncate_for_platform_returns_empty_string_when_empty():
    ops = _StubMessageOps()
    result = ops._truncate_for_platform("", None, 100)
    assert result == ""


# ---------------------------------------------------------------------------
# edit_message — null/empty message_id guard
# ---------------------------------------------------------------------------


async def test_edit_message_returns_false_for_empty_message_id():
    ops = _StubMessageOps()
    session = MagicMock()
    session.session_id = "sess-1"
    result = await ops.edit_message(session, "", text="hello")
    assert result is False


async def test_edit_message_returns_true_when_content_hash_unchanged():
    ops = _StubMessageOps()
    session = _make_session()
    metadata = MessageMetadata()
    # Pre-load the hash to simulate a previously sent message with identical content
    content_hash = ops._content_hash("hello", None, None)
    ops._last_edit_hash["42"] = content_hash
    result = await ops.edit_message(session, "42", text="hello", metadata=metadata)
    assert result is True


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


async def test_send_message_suppresses_telegram_reflection():
    ops = _StubMessageOps()
    session = _make_session()
    metadata = MessageMetadata(reflection_origin="telegram")

    result = await ops.send_message(session, "hello", metadata=metadata)

    assert result == "0"
    ops.bot.send_message.assert_not_awaited()
    assert ops.waited_for_topic == []


async def test_send_message_formats_cross_source_reflection_before_send():
    ops = _StubMessageOps()
    session = _make_session(topic_id=23)
    metadata = MessageMetadata(reflection_origin="discord", reflection_actor_name="Alice")

    result = await ops.send_message(session, "hello", metadata=metadata)

    assert result == "101"
    ops.bot.send_message.assert_awaited_once()
    call = ops.bot.send_message.await_args
    assert call.kwargs["message_thread_id"] == 23
    assert call.kwargs["text"].startswith("Alice @ DISCORD:\n\nhello")
    assert call.kwargs["text"].endswith("\n\n---\n")
    assert ops.waited_for_topic == [(23, "Test Session")]


async def test_send_message_raises_when_topic_id_is_missing():
    ops = _StubMessageOps()
    session = _make_session(topic_id=None)

    try:
        await ops.send_message(session, "hello")
    except RuntimeError as exc:
        assert "Telegram topic_id missing" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when topic_id is missing")


# ---------------------------------------------------------------------------
# edit_message pending edit path
# ---------------------------------------------------------------------------


async def test_edit_message_updates_existing_pending_edit_context():
    ops = _StubMessageOps()
    session = _make_session()
    ops._edit_message_with_retry = AsyncMock()
    existing = EditContext(message_id="42", text="old", reply_markup=None, parse_mode=None)
    ops._pending_edits["42"] = existing
    metadata = MessageMetadata(parse_mode="MarkdownV2")

    result = await ops.edit_message(session, "42", text="new", metadata=metadata)

    assert result is True
    assert existing.text == "new"
    assert existing.parse_mode == "MarkdownV2"
    ops._edit_message_with_retry.assert_not_awaited()
