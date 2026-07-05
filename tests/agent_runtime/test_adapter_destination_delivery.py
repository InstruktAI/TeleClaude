"""Preservation + betterment bindings for per-adapter Destination delivery.

Proves each concrete adapter's delivery bodies address the resolved
Destination identically to the pre-seam session-derived behavior (Discord
channel/thread + metadata.channel_id override precedence; WhatsApp
phone_number delivery and edit/delete no-op), and proves the three named
Telegram betterments carried by the seam flip: edit_message/delete_message/
send_file now address the private-chat chat_id instead of the unset
supergroup_id / dead topic_id gate.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from telegram import Message

from teleclaude.adapters.discord.input_handlers import InputHandlersMixin as DiscordInputHandlersMixin
from teleclaude.adapters.discord.message_ops import MessageOperationsMixin as DiscordMessageOperationsMixin
from teleclaude.adapters.telegram.message_ops import MessageOperationsMixin as TelegramMessageOperationsMixin
from teleclaude.adapters.whatsapp_adapter import WhatsAppAdapter
from teleclaude.core.delivery import Destination
from teleclaude.core.origins import InputOrigin

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Discord: metadata.channel_id override + session-derived channel/thread
# ---------------------------------------------------------------------------


class _FakeDiscordChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.sends: list[str] = []

    async def send(self, text: str) -> object:
        self.sends.append(text)
        return SimpleNamespace(id=f"bot-{len(self.sends)}")


class _FakeDiscordClient:
    """Fakes only the network boundary discord.py's Client exposes."""

    def __init__(self, channels: dict[int, _FakeDiscordChannel]) -> None:
        self._channels = channels

    def get_channel(self, channel_id: int) -> _FakeDiscordChannel | None:
        return self._channels.get(channel_id)


class _DiscordBoundary(DiscordInputHandlersMixin, DiscordMessageOperationsMixin):
    """Discord delivery boundary exercising the production destination resolver
    (``InputHandlersMixin._resolve_destination_channel`` / ``_get_channel``);
    only the network boundary (``self._client``) is faked."""

    def __init__(self, channels: dict[int, _FakeDiscordChannel]) -> None:
        self._client = _FakeDiscordClient(channels)
        self.max_message_size = 2000
        self._TRUNCATION_SUFFIX = "..."
        self.ADAPTER_KEY = InputOrigin.DISCORD.value
        self._reflection_webhook_cache: dict[int, object] = {}
        self._discord = SimpleNamespace()

    @staticmethod
    def _is_thread_channel(channel: object) -> bool:
        return bool(getattr(channel, "is_thread", False))

    @staticmethod
    def _require_async_callable(fn: object, *, label: str) -> Any:
        assert callable(fn), f"{label} is not callable"
        return fn

    @staticmethod
    def _parse_optional_int(value: object) -> int | None:
        if value is None:
            return None
        return int(str(value))


async def test_discord_send_message_addresses_session_derived_channel() -> None:
    """adapter-client Router invariant: Discord addresses the session-provisioned channel by default."""
    session_channel = _FakeDiscordChannel(111)
    boundary = _DiscordBoundary({111: session_channel})

    destination = Destination(platform="discord", session_id="sess-1", channel_id=111)
    await boundary.send_message(destination, "hello")

    assert session_channel.sends == ["hello"]


async def test_discord_metadata_channel_id_override_wins_over_session_channel() -> None:
    """adapter-client Router invariant: metadata.channel_id override precedence is preserved."""
    session_channel = _FakeDiscordChannel(111)
    override_channel = _FakeDiscordChannel(222)
    boundary = _DiscordBoundary({111: session_channel, 222: override_channel})

    # The Destination already carries the resolved (overridden) coord — resolve_destination()
    # applies metadata.channel_id -> thread_id -> channel_id precedence upstream of the adapter.
    destination = Destination(platform="discord", session_id="sess-1", channel_id=222)
    await boundary.send_message(destination, "override target")

    assert override_channel.sends == ["override target"]
    assert session_channel.sends == []


# ---------------------------------------------------------------------------
# Telegram: chat_id addressing (betterment — fixes 3 live outbound bugs)
# ---------------------------------------------------------------------------


class _FakeTelegramBot:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []  # guard: loose-dict - captured call kwargs
        self.edited: list[dict[str, object]] = []  # guard: loose-dict - captured call kwargs
        self.deleted: list[dict[str, object]] = []  # guard: loose-dict - captured call kwargs
        self.documents: list[dict[str, object]] = []  # guard: loose-dict - captured call kwargs

    async def send_message(self, **kwargs: object) -> Message:
        self.sent.append(kwargs)
        return cast(Message, SimpleNamespace(message_id=len(self.sent)))

    async def edit_message_text(self, **kwargs: object) -> None:
        self.edited.append(kwargs)

    async def delete_message(self, **kwargs: object) -> None:
        self.deleted.append(kwargs)

    async def send_document(self, **kwargs: object) -> Message:
        self.documents.append(kwargs)
        return cast(Message, SimpleNamespace(message_id=len(self.documents)))


class _TelegramBoundary(TelegramMessageOperationsMixin):
    """Minimal Telegram delivery boundary over a fake bot; no real chat/topic state."""

    def __init__(self, bot: _FakeTelegramBot) -> None:
        self._bot = bot
        self.supergroup_id = -100999  # the wrong chat the pre-fix bugs addressed
        self._pending_edits = {}
        self._last_edit_hash = {}

    @property
    def bot(self) -> _FakeTelegramBot:  # type: ignore[override]
        return self._bot

    def _ensure_started(self) -> None:
        return None


def _telegram_destination(chat_id: int) -> Destination:
    return Destination(platform="telegram", session_id="sess-tg", chat_id=chat_id)


async def test_telegram_send_message_addresses_private_chat_id() -> None:
    """Preserved: send_message already addressed the private chat_id before the seam flip."""
    bot = _FakeTelegramBot()
    boundary = _TelegramBoundary(bot)

    await boundary.send_message(_telegram_destination(555), "hi")

    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == 555


async def test_telegram_edit_message_addresses_chat_id_not_supergroup() -> None:
    """Betterment: edit_message no longer references the unset supergroup_id (live bug #1)."""
    bot = _FakeTelegramBot()
    boundary = _TelegramBoundary(bot)

    result = await boundary.edit_message(_telegram_destination(555), "42", "edited text")

    assert result is True
    assert len(bot.edited) == 1
    assert bot.edited[0]["chat_id"] == 555
    assert bot.edited[0]["chat_id"] != boundary.supergroup_id


async def test_telegram_delete_message_addresses_chat_id_not_supergroup() -> None:
    """Betterment: delete_message no longer references the unset supergroup_id (live bug #2)."""
    bot = _FakeTelegramBot()
    boundary = _TelegramBoundary(bot)

    result = await boundary.delete_message(_telegram_destination(555), "42")

    assert result is True
    assert len(bot.deleted) == 1
    assert bot.deleted[0]["chat_id"] == 555
    assert bot.deleted[0]["chat_id"] != boundary.supergroup_id


async def test_telegram_send_file_delivers_to_private_chat(tmp_path: Any) -> None:
    """Betterment: send_file delivers via chat_id, no longer gated on the always-absent topic_id (live bug #3)."""
    bot = _FakeTelegramBot()
    boundary = _TelegramBoundary(bot)
    file_path = tmp_path / "report.txt"
    file_path.write_text("contents")

    message_id = await boundary.send_file(_telegram_destination(555), str(file_path))

    first_document_message_id = "1"
    assert message_id == first_document_message_id
    assert len(bot.documents) == 1
    assert bot.documents[0]["chat_id"] == 555
    assert bot.documents[0]["message_thread_id"] is None


async def test_telegram_delivery_skips_when_no_chat_id_resolved() -> None:
    """No chat_id resolved (no user_id in origin_metadata) -> skip, matching the prior no-user_id skip."""
    bot = _FakeTelegramBot()
    boundary = _TelegramBoundary(bot)
    destination = Destination(platform="telegram", session_id="sess-tg", chat_id=None)
    skipped_send_result = ""

    assert await boundary.send_message(destination, "hi") == skipped_send_result
    assert await boundary.edit_message(destination, "42", "text") is False
    assert await boundary.delete_message(destination, "42") is False
    assert bot.sent == []
    assert bot.edited == []
    assert bot.deleted == []


# ---------------------------------------------------------------------------
# WhatsApp: phone_number delivery preserved; edit/delete stay no-ops
# ---------------------------------------------------------------------------


async def test_whatsapp_send_message_addresses_phone_number(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserved: WhatsApp send_message addresses the resolved phone_number."""
    adapter = WhatsAppAdapter(client=SimpleNamespace())
    sent_to: list[str] = []
    fake_wamid = "wamid.1"

    async def _fake_send_text_message(phone_number: str, text: str) -> str:
        del text
        sent_to.append(phone_number)
        return fake_wamid

    monkeypatch.setattr(adapter, "_send_text_message", _fake_send_text_message)

    destination = Destination(platform="whatsapp", session_id="sess-wa", phone_number="+15551234567")
    message_id = await adapter.send_message(destination, "hello")

    assert message_id == fake_wamid
    assert sent_to == ["+15551234567"]


async def test_whatsapp_send_message_without_phone_number_raises() -> None:
    """Preserved: missing phone_number still raises (no silent drop)."""
    adapter = WhatsAppAdapter(client=SimpleNamespace())
    destination = Destination(platform="whatsapp", session_id="sess-wa", phone_number=None)

    with pytest.raises(ValueError):
        await adapter.send_message(destination, "hello")


async def test_whatsapp_edit_and_delete_remain_no_ops() -> None:
    """Preserved: WhatsApp has no edit/delete API — both remain inert no-ops."""
    adapter = WhatsAppAdapter(client=SimpleNamespace())
    destination = Destination(platform="whatsapp", session_id="sess-wa", phone_number="+15551234567")

    assert await adapter.edit_message(destination, "wamid.1", "new text") is False
    assert await adapter.delete_message(destination, "wamid.1") is False
