"""Preservation bindings for the channel-lifecycle relocation.

Proves the relocation (channel-lifecycle methods off the universal
``BaseAdapter`` contract, admin/Discord-only) preserves Discord behavior
identically while non-Discord adapters — which no longer carry these
methods at all — are never dispatched to and never raise ``AttributeError``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import teleclaude.adapters.ui_adapter as ui_adapter_mod
import teleclaude.core.adapter_client._channels as channels_mod
import teleclaude.core.adapter_client._output as output_mod
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.adapter_client import AdapterRuntime
from teleclaude.core.db import Db
from teleclaude.core.delivery import Destination
from teleclaude.core.models import ChannelMetadata, MessageMetadata, Session
from teleclaude.core.origins import InputOrigin
from tests.agent_runtime._fake_ui_adapter import DiscordChannelLifecycleMixin, NoOpChannelLifecycleMixin

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


def _patch_db(monkeypatch: pytest.MonkeyPatch, db: Db) -> None:
    monkeypatch.setattr(output_mod, "db", db)
    monkeypatch.setattr(channels_mod, "db", db)
    monkeypatch.setattr(ui_adapter_mod, "db", db)


class _FakeDiscordAdapter(DiscordChannelLifecycleMixin, NoOpChannelLifecycleMixin, UiAdapter):
    """Fake Discord adapter: the only fake that still carries channel lifecycle."""

    def __init__(self) -> None:
        super().__init__(client=SimpleNamespace())
        self.ADAPTER_KEY = InputOrigin.DISCORD.value
        self.create_channel_calls: list[Session] = []
        self.update_channel_title_calls: list[Session] = []
        self.delete_channel_calls: list[Session] = []
        self.sent: list[Destination] = []

    async def send_message(
        self,
        destination: Destination,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> str:
        del text, metadata, multi_message
        self.sent.append(destination)
        return f"msg-{len(self.sent)}"

    def get_max_message_length(self) -> int:
        return 2000

    async def ensure_channel(self, session: Session) -> Session:
        """Mirror Discord's real funnel: provision only when no thread exists yet."""
        discord_section = session.get_origin_section("discord")
        if discord_section.get("thread_id") is not None:
            return session
        await self.create_channel(session, "title", ChannelMetadata())
        return session


class _FakeNonDiscordAdapter(NoOpChannelLifecycleMixin, UiAdapter):
    """Fake non-Discord (e.g. Telegram) adapter: no channel-lifecycle methods at all."""

    def __init__(self, adapter_key: str) -> None:
        super().__init__(client=SimpleNamespace())
        self.ADAPTER_KEY = adapter_key
        self.sent: list[Destination] = []

    async def send_message(
        self,
        destination: Destination,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> str:
        del text, metadata, multi_message
        self.sent.append(destination)
        return f"msg-{len(self.sent)}"

    def get_max_message_length(self) -> int:
        return 4096


async def _make_db() -> Db:
    db = Db(":memory:")
    await db.initialize()
    return db


def _session(*, origin: str) -> Session:
    return Session(
        session_id="sess-lifecycle",
        computer_name="local",
        tmux_session_name="tc-sess-lifecycle",
        title="lifecycle",
        last_input_origin=origin,
        origin_metadata={},
    )


async def test_title_sync_reaches_discord_only_non_discord_origin_never_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """session_title.py path: non-Discord origin + Discord admin lane -> Discord renames once."""
    db = await _make_db()
    try:
        _patch_db(monkeypatch, db)
        session = _session(origin=InputOrigin.TELEGRAM.value)
        await db.create_session(
            computer_name=session.computer_name,
            tmux_session_name=session.tmux_session_name,
            last_input_origin=session.last_input_origin,
            title=session.title,
            session_id=session.session_id,
            emit_session_started=False,
        )
        await db.update_origin_metadata(session.session_id, "discord", {"thread_id": 999})

        runtime = AdapterRuntime()
        telegram_fake = _FakeNonDiscordAdapter(InputOrigin.TELEGRAM.value)
        discord_fake = _FakeDiscordAdapter()
        runtime.adapters[InputOrigin.TELEGRAM.value] = telegram_fake
        runtime.adapters[InputOrigin.DISCORD.value] = discord_fake

        # The non-Discord fake has no update_channel_title at all — matching the
        # final no-lifecycle UiAdapter shape post-relocation.
        assert not hasattr(telegram_fake, "update_channel_title")

        succeeded = await runtime.update_channel_title(session)

        assert succeeded is True
        assert len(discord_fake.update_channel_title_calls) == 1
        assert discord_fake.create_channel_calls == []
    finally:
        await db.close()


async def test_cleanup_deletes_discord_only_non_discord_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """session_cleanup.py path: Discord's delete_channel invoked once, non-Discord untouched."""
    db = await _make_db()
    try:
        _patch_db(monkeypatch, db)
        session = _session(origin=InputOrigin.TELEGRAM.value)
        await db.create_session(
            computer_name=session.computer_name,
            tmux_session_name=session.tmux_session_name,
            last_input_origin=session.last_input_origin,
            title=session.title,
            session_id=session.session_id,
            emit_session_started=False,
        )
        await db.update_origin_metadata(session.session_id, "discord", {"thread_id": 999})

        runtime = AdapterRuntime()
        telegram_fake = _FakeNonDiscordAdapter(InputOrigin.TELEGRAM.value)
        discord_fake = _FakeDiscordAdapter()
        runtime.adapters[InputOrigin.TELEGRAM.value] = telegram_fake
        runtime.adapters[InputOrigin.DISCORD.value] = discord_fake

        assert not hasattr(telegram_fake, "delete_channel")

        succeeded = await runtime.delete_channel(session)

        assert succeeded is True
        assert len(discord_fake.delete_channel_calls) == 1
        # Teardown never provisions — the fake's create_channel is not called.
        assert discord_fake.create_channel_calls == []
    finally:
        await db.close()


async def test_provisioning_still_creates_discord_channel_without_adapterclient_broadcast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ensure_ui_channels funnel: Discord create_channel invoked via ensure_channel, no broadcast method."""
    db = await _make_db()
    try:
        _patch_db(monkeypatch, db)
        session = _session(origin=InputOrigin.DISCORD.value)
        await db.create_session(
            computer_name=session.computer_name,
            tmux_session_name=session.tmux_session_name,
            last_input_origin=session.last_input_origin,
            title=session.title,
            session_id=session.session_id,
            emit_session_started=False,
        )
        # No discord thread_id yet -> ensure_channel must provision one.

        runtime = AdapterRuntime()
        discord_fake = _FakeDiscordAdapter()
        runtime.adapters[InputOrigin.DISCORD.value] = discord_fake

        # The orphaned all-adapter broadcast is gone entirely.
        assert not hasattr(runtime, "create_channel")

        await runtime.ensure_ui_channels(session)

        assert len(discord_fake.create_channel_calls) == 1
    finally:
        await db.close()


async def test_non_discord_only_suppresses_lifecycle_with_no_attribute_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Discord registered: update_channel_title/delete_channel no-op, no AttributeError."""
    db = await _make_db()
    try:
        _patch_db(monkeypatch, db)
        session = _session(origin=InputOrigin.TELEGRAM.value)
        await db.create_session(
            computer_name=session.computer_name,
            tmux_session_name=session.tmux_session_name,
            last_input_origin=session.last_input_origin,
            title=session.title,
            session_id=session.session_id,
            emit_session_started=False,
        )

        runtime = AdapterRuntime()
        telegram_fake = _FakeNonDiscordAdapter(InputOrigin.TELEGRAM.value)
        runtime.adapters[InputOrigin.TELEGRAM.value] = telegram_fake

        title_result = await runtime.update_channel_title(session)
        delete_result = await runtime.delete_channel(session)

        assert title_result is False
        assert delete_result is False
    finally:
        await db.close()
