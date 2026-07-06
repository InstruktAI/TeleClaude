"""Zero-regression preservation checks for admin-reflection-mixin-extraction.

Pins escalation/relay/handback behavior across the owned-column rename
(relay_discord_channel_id -> relay_channel_id), the AdminReflectionMixin
extraction, the handback pipeline rewrite, and the AdminReflectionAdapter
DIP fix — proving no observable behavior changed except the intended
handback-pipeline delta (asserted as its new correct behavior).
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import aiosqlite
import pytest
from httpx import AsyncClient
from syrupy.assertion import SnapshotAssertion

import teleclaude.adapters.discord.relay_ops as relay_ops_mod
import teleclaude.core.command_service as command_service_mod
from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord.relay_ops import AdminReflectionMixin
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.protocols import AdminReflectionAdapter
from teleclaude.types.commands import ProcessMessageCommand, SystemCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SESSION_ID = "session-relay-1"
_THREAD_ID = 555111
_CUSTOMER_SESSION_ID = "session-customer-1"
_OLD_RELAY_COLUMN = "relay_discord_channel_id"
_NEW_RELAY_COLUMN = "relay_channel_id"
_RELAY_STATUS_ACTIVE = "active"
_CUSTOMER_NAME = "Ann"


# =============================================================================
# Task 1 — owned-column rename: migration golden fixture
# =============================================================================


async def test_migration_048_renames_column_preserving_populated_value(tmp_path: Path) -> None:
    """The 048 migration renames the column and preserves populated values."""
    migration = importlib.import_module("teleclaude.core.migrations.048_rename_relay_discord_channel_id")
    db_path = tmp_path / "core.db"

    conn = await aiosqlite.connect(str(db_path))
    try:
        await conn.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, relay_discord_channel_id TEXT)")
        await conn.execute(
            "INSERT INTO sessions (session_id, relay_discord_channel_id) VALUES (?, ?)",
            (_SESSION_ID, str(_THREAD_ID)),
        )
        await conn.commit()

        await migration.up(conn)

        columns_cursor = await conn.execute("SELECT name FROM pragma_table_info('sessions')")
        columns = {str(row[0]) for row in await columns_cursor.fetchall()}
        assert _OLD_RELAY_COLUMN not in columns
        assert _NEW_RELAY_COLUMN in columns

        value_cursor = await conn.execute("SELECT relay_channel_id FROM sessions WHERE session_id = ?", (_SESSION_ID,))
        row = await value_cursor.fetchone()
        assert row is not None
        assert row[0] == str(_THREAD_ID)
    finally:
        await conn.close()


async def test_migration_048_is_idempotent_when_column_already_renamed(tmp_path: Path) -> None:
    """A second application of the migration is a no-op (guard clause)."""
    migration = importlib.import_module("teleclaude.core.migrations.048_rename_relay_discord_channel_id")
    db_path = tmp_path / "core.db"

    conn = await aiosqlite.connect(str(db_path))
    try:
        await conn.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, relay_channel_id TEXT)")
        await conn.execute(
            "INSERT INTO sessions (session_id, relay_channel_id) VALUES (?, ?)",
            (_SESSION_ID, str(_THREAD_ID)),
        )
        await conn.commit()

        await migration.up(conn)

        value_cursor = await conn.execute("SELECT relay_channel_id FROM sessions WHERE session_id = ?", (_SESSION_ID,))
        row = await value_cursor.fetchone()
        assert row is not None
        assert row[0] == str(_THREAD_ID)
    finally:
        await conn.close()


# =============================================================================
# AdminReflectionMixin harness — relay forward / handback / escalation-thread
# =============================================================================


class _FakeThread:
    def __init__(self, *, history: list[object] | None = None) -> None:
        self.sent: list[str] = []
        self._history = history or []

    async def send(self, text: str) -> None:
        self.sent.append(text)

    def history(self, *, after: object, limit: int) -> AsyncIterator[object]:
        del after, limit
        return self._iter_history()

    async def _iter_history(self) -> AsyncIterator[object]:
        for msg in self._history:
            yield msg


@dataclass(frozen=True, slots=True)
class _Author:
    display_name: str
    bot: bool = False


@dataclass(frozen=True, slots=True)
class _HistoryMessage:
    content: str
    author: _Author


@dataclass(frozen=True, slots=True)
class _Channel:
    id: int


@dataclass(frozen=True, slots=True)
class _RelayMessage:
    channel: _Channel
    author: _Author
    content: str = ""


class _FakeForum:
    is_forum = True

    def __init__(self, *, forum_id: int) -> None:
        self.id = forum_id


@dataclass
class _ClientCall:
    session: Session
    text: str
    metadata: MessageMetadata
    ephemeral: bool


@dataclass(frozen=True, slots=True)
class _RelayStateUpdate:
    session_id: str
    relay_status: str | None
    relay_channel_id: str | None
    relay_started_at: str | None
    lifecycle_status: str


@dataclass(frozen=True, slots=True)
class _EscalationThreadCall:
    customer_name: str
    reason: str
    context_summary: str | None
    session_id: str


class _FakeAdapterClient:
    def __init__(self) -> None:
        self.calls: list[_ClientCall] = []

    async def send_message(self, *, session: Session, text: str, metadata: MessageMetadata, ephemeral: bool) -> str:
        self.calls.append(_ClientCall(session=session, text=text, metadata=metadata, ephemeral=ephemeral))
        return "sent-message-id"


class _AdminReflectionHarness(AdminReflectionMixin):
    """Minimal host exposing only what AdminReflectionMixin's methods touch."""

    def __init__(
        self,
        *,
        client: _FakeAdapterClient,
        channels: dict[int, object] | None = None,
        escalation_channel_id: int | None = None,
        create_forum_result: tuple[int, str] | None = None,
    ) -> None:
        self._client = object()
        self.client = cast("AdapterClient", client)
        self._channels = channels or {}
        self._escalation_channel_id = escalation_channel_id
        self._create_forum_result = create_forum_result
        self.create_forum_calls: list[tuple[object, str, str]] = []

    @staticmethod
    def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]:
        del label
        return cast(Callable[..., Awaitable[object]], fn)

    async def _get_channel(self, channel_id: int) -> object | None:
        return self._channels.get(channel_id)

    @staticmethod
    def _is_forum_channel(channel: object) -> bool:
        del channel
        return True

    async def _create_forum_thread(self, forum_channel: object, *, title: str, content: str = "") -> tuple[int, str]:
        self.create_forum_calls.append((forum_channel, title, content))
        assert self._create_forum_result is not None
        return self._create_forum_result


def _session(*, relay_channel_id: str | None = str(_THREAD_ID)) -> Session:
    return Session(
        session_id=_SESSION_ID,
        computer_name="TestComputer",
        tmux_session_name="tmux-relay",
        title="relay session",
        last_input_origin="telegram",
        relay_status="active",
        relay_channel_id=relay_channel_id,
        relay_started_at=datetime(2026, 7, 5, tzinfo=UTC),
    )


async def test_forward_to_relay_thread_diverts_customer_message(snapshot: SnapshotAssertion) -> None:
    """Customer traffic during an active relay is diverted into the relay thread."""
    thread = _FakeThread()
    harness = _AdminReflectionHarness(client=_FakeAdapterClient(), channels={_THREAD_ID: thread})
    session = _session()
    message = _RelayMessage(channel=_Channel(id=_THREAD_ID), author=_Author(display_name="Ann"))

    await harness.forward_to_relay_thread(session, "I need help", message)

    assert thread.sent == [snapshot]


async def test_forward_to_relay_thread_noop_when_no_relay_channel() -> None:
    """No relay channel set means no diversion attempt."""
    thread = _FakeThread()
    harness = _AdminReflectionHarness(client=_FakeAdapterClient(), channels={_THREAD_ID: thread})
    session = _session(relay_channel_id=None)
    message = _RelayMessage(channel=_Channel(id=_THREAD_ID), author=_Author(display_name="Ann"))

    await harness.forward_to_relay_thread(session, "hello", message)

    assert thread.sent == []


async def test_handle_relay_thread_message_forwards_admin_text_to_customer(
    monkeypatch: pytest.MonkeyPatch, snapshot: SnapshotAssertion
) -> None:
    """A non-handback admin message in the relay thread reaches the customer."""
    client = _FakeAdapterClient()
    harness = _AdminReflectionHarness(client=client)
    session = _session()

    class _FakeDb:
        async def get_session_by_field(self, field_name: str, value: str) -> Session | None:
            assert field_name == _NEW_RELAY_COLUMN
            return session if value == str(_THREAD_ID) else None

    monkeypatch.setattr(relay_ops_mod, "db", _FakeDb())

    message = _RelayMessage(channel=_Channel(id=_THREAD_ID), author=_Author(display_name="Ann the Admin"))

    await harness.handle_relay_thread_message(message, "the customer should see this")

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call.session is session
    assert call.ephemeral is False
    assert call.text == snapshot


async def test_handle_relay_thread_message_orphaned_thread_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """A relay-thread message with no matching session is dropped, not raised."""
    client = _FakeAdapterClient()
    harness = _AdminReflectionHarness(client=client)

    class _FakeDb:
        async def get_session_by_field(self, field_name: str, value: str) -> Session | None:
            del field_name, value
            return None

    monkeypatch.setattr(relay_ops_mod, "db", _FakeDb())

    message = _RelayMessage(channel=_Channel(id=_THREAD_ID), author=_Author(display_name="Someone"))

    await harness.handle_relay_thread_message(message, "orphaned")

    assert client.calls == []


async def test_agent_handback_routes_through_process_message_and_clears_relay_state(
    monkeypatch: pytest.MonkeyPatch, cluster_event_bus: None, snapshot: SnapshotAssertion
) -> None:
    """@agent handback compiles context, injects via process_message (not tmux), clears relay state."""
    thread = _FakeThread(
        history=[
            _HistoryMessage(content="**Ann** (telegram): I need help", author=_Author(display_name="bot", bot=True)),
            _HistoryMessage(content="On it — one moment", author=_Author(display_name="Operator", bot=False)),
        ]
    )
    harness = _AdminReflectionHarness(client=_FakeAdapterClient(), channels={_THREAD_ID: thread})
    session = _session()

    update_calls: list[_RelayStateUpdate] = []

    class _FakeDb:
        async def get_session_by_field(self, field_name: str, value: str) -> Session | None:
            assert field_name == _NEW_RELAY_COLUMN
            return session if value == str(_THREAD_ID) else None

        async def update_session(
            self,
            session_id: str,
            *,
            relay_status: str | None,
            relay_channel_id: str | None,
            relay_started_at: str | None,
            lifecycle_status: str,
        ) -> None:
            update_calls.append(
                _RelayStateUpdate(
                    session_id=session_id,
                    relay_status=relay_status,
                    relay_channel_id=relay_channel_id,
                    relay_started_at=relay_started_at,
                    lifecycle_status=lifecycle_status,
                )
            )

    process_message_calls: list[ProcessMessageCommand] = []

    class _FakeCommandService:
        async def process_message(self, cmd: ProcessMessageCommand) -> None:
            process_message_calls.append(cmd)

    ended_events: list[str] = []

    async def _record_ended(_event: str, ctx: object) -> None:
        ended_events.append(getattr(ctx, "session_id", ""))

    # event_bus.emit is fire-and-forget from the mixin (no await at the call
    # site); capture the scheduled task here so the test can await completion
    # of the in-process dispatch deterministically.
    emitted_tasks: list[asyncio.Task[str]] = []
    real_emit = relay_ops_mod.event_bus.emit

    def _capturing_emit(*args: object, **kwargs: object) -> asyncio.Task[str]:
        task = cast("asyncio.Task[str]", real_emit(*args, **kwargs))
        emitted_tasks.append(task)
        return task

    monkeypatch.setattr(relay_ops_mod, "db", _FakeDb())
    monkeypatch.setattr(relay_ops_mod, "get_command_service", lambda: _FakeCommandService())
    monkeypatch.setattr(relay_ops_mod.event_bus, "emit", _capturing_emit)
    relay_ops_mod.event_bus.subscribe("session.escalation_ended", _record_ended)

    message = _RelayMessage(channel=_Channel(id=_THREAD_ID), author=_Author(display_name="Operator"))

    await harness.handle_relay_thread_message(message, "@agent take it back")
    for task in emitted_tasks:
        await task

    # Injected through the inbound pipeline, not a raw tmux bypass.
    assert len(process_message_calls) == 1
    cmd = process_message_calls[0]
    assert cmd.session_id == _SESSION_ID
    assert cmd.origin == InputOrigin.DISCORD.value
    assert cmd.text == snapshot

    # Relay state cleared and lifecycle restored.
    assert update_calls == [
        _RelayStateUpdate(
            session_id=_SESSION_ID,
            relay_status=None,
            relay_channel_id=None,
            relay_started_at=None,
            lifecycle_status="active",
        )
    ]

    # Handback still emits session.escalation_ended exactly once.
    assert ended_events == [_SESSION_ID]


async def test_create_escalation_thread_creates_forum_thread_and_returns_id(snapshot: SnapshotAssertion) -> None:
    """create_escalation_thread opens a thread in the configured escalation forum."""
    forum = _FakeForum(forum_id=7)
    harness = _AdminReflectionHarness(
        client=_FakeAdapterClient(),
        channels={7: forum},
        escalation_channel_id=7,
        create_forum_result=(_THREAD_ID, "starter-message-id"),
    )

    thread_id = await harness.create_escalation_thread(
        customer_name=_CUSTOMER_NAME,
        reason="needs a human",
        context_summary="frustrated with billing",
        session_id=_CUSTOMER_SESSION_ID,
    )

    assert thread_id == _THREAD_ID
    assert len(harness.create_forum_calls) == 1
    called_forum, title, body = harness.create_forum_calls[0]
    assert called_forum is forum
    assert title == _CUSTOMER_NAME
    assert body == snapshot


async def test_create_escalation_thread_requires_configured_channel() -> None:
    """No escalation_channel_id configured fails loud, not silently."""
    harness = _AdminReflectionHarness(client=_FakeAdapterClient(), escalation_channel_id=None)

    with pytest.raises(AdapterError):
        await harness.create_escalation_thread(
            customer_name="Ann", reason="r", context_summary=None, session_id=_CUSTOMER_SESSION_ID
        )


# =============================================================================
# Task 5 — DIP fix: escalate_session resolves AdminReflectionAdapter, not DiscordAdapter
# =============================================================================


class _FakeAdminAdapter:
    """Satisfies AdminReflectionAdapter structurally — no import of the Protocol needed."""

    def __init__(self, *, thread_id: int) -> None:
        self._thread_id = thread_id
        self.calls: list[_EscalationThreadCall] = []

    async def create_escalation_thread(self, **kwargs: str | None) -> int:
        self.calls.append(
            _EscalationThreadCall(
                customer_name=str(kwargs.get("customer_name") or ""),
                reason=str(kwargs.get("reason") or ""),
                context_summary=kwargs.get("context_summary"),
                session_id=str(kwargs.get("session_id") or ""),
            )
        )
        return self._thread_id


async def test_fake_admin_adapter_satisfies_protocol_structurally() -> None:
    """Structural (duck-typed) satisfaction — no adapter-side import required."""
    assert isinstance(_FakeAdminAdapter(thread_id=1), AdminReflectionAdapter)


async def test_escalate_session_resolves_admin_adapter_and_persists_relay_state(
    api: AsyncClient, cluster_event_bus: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """escalate_session resolves the admin adapter via the Protocol and writes the renamed column."""
    monkeypatch.setattr(command_service_mod, "db", api.db)
    await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name="tmux-customer",
        last_input_origin="telegram",
        title="customer session",
        session_id=_CUSTOMER_SESSION_ID,
        human_role="customer",
        lifecycle_status="active",
        emit_session_started=False,
    )

    fake_adapter = _FakeAdminAdapter(thread_id=_THREAD_ID)
    svc = get_command_service()
    svc.client.adapters = {"discord": fake_adapter}  # type: ignore[dict-item]

    cmd = SystemCommand(
        command="escalate_session",
        session_id=_CUSTOMER_SESSION_ID,
        data={"customer_name": "Ann", "reason": "needs a human", "context_summary": "billing dispute"},
    )

    result = await svc.escalate_session(cmd)

    assert result == {"status": "accepted", "thread_id": _THREAD_ID}
    assert len(fake_adapter.calls) == 1

    updated = await api.db.get_session(_CUSTOMER_SESSION_ID)
    assert updated is not None
    assert updated.relay_status == _RELAY_STATUS_ACTIVE
    assert updated.relay_channel_id == str(_THREAD_ID)

    # escalate_session leaves lifecycle_status="escalated" (not "active"), so the
    # by-field lookup must opt in to non-active sessions to resolve it.
    resolved = await api.db.get_session_by_field(_NEW_RELAY_COLUMN, str(_THREAD_ID), include_initializing=True)
    assert resolved is not None
    assert resolved.session_id == _CUSTOMER_SESSION_ID


async def test_escalate_session_fails_when_no_admin_reflection_adapter_registered(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No adapter satisfying AdminReflectionAdapter is registered -> fails loud, not silently."""
    monkeypatch.setattr(command_service_mod, "db", api.db)
    await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name="tmux-customer-2",
        last_input_origin="telegram",
        title="customer session",
        session_id="session-customer-2",
        human_role="customer",
        lifecycle_status="active",
        emit_session_started=False,
    )

    svc = get_command_service()
    svc.client.adapters = {}

    cmd = SystemCommand(
        command="escalate_session",
        session_id="session-customer-2",
        data={"customer_name": "Ann", "reason": "r", "context_summary": None},
    )

    with pytest.raises(ValueError):
        await svc.escalate_session(cmd)
