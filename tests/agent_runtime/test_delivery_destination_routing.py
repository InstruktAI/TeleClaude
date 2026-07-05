"""Preservation bindings for project/spec/session-output-routing.

Proves the destination-addressed delivery seam (Router + Destination)
delivers to identical recipients as the pre-seam session-addressed dispatch:
ORIGIN_ONLY / ADMIN_ONLY / DUAL scope selection, Discord-only admin
reflection, and the ``metadata.channel_id`` override precedence.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import teleclaude.adapters.ui.delivery_mixin as ui_delivery_mixin_mod
import teleclaude.adapters.ui_adapter as ui_adapter_mod
import teleclaude.core.adapter_client._channels as channels_mod
import teleclaude.core.adapter_client._output as output_mod
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.adapter_client import AdapterRuntime
from teleclaude.core.db import Db
from teleclaude.core.delivery import DeliveryScope, Destination, Router
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.core.origins import InputOrigin
from tests.agent_runtime._fake_ui_adapter import NoOpChannelLifecycleMixin

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


def _patch_db(monkeypatch: pytest.MonkeyPatch, db: Db) -> None:
    monkeypatch.setattr(output_mod, "db", db)
    monkeypatch.setattr(channels_mod, "db", db)
    monkeypatch.setattr(ui_adapter_mod, "db", db)
    monkeypatch.setattr(ui_delivery_mixin_mod, "db", db)


class _RecordingUiAdapter(NoOpChannelLifecycleMixin, UiAdapter):
    """Records every Destination it was asked to deliver to."""

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
        return 2000

    def get_ai_session_poll_interval(self) -> float:
        return 1.0


async def _make_db() -> Db:
    db = Db(":memory:")
    await db.initialize()
    return db


async def _set_telegram_user_id(db: Db, session_id: str, user_id: int) -> None:
    """Set the top-level origin_metadata ``user_id`` Telegram delivery resolves against.

    Telegram stores its chat identity at the top level of ``origin_metadata``
    (not nested under a "telegram" section like Discord/WhatsApp) — see
    ``resolve_destination()``'s telegram branch. ``update_origin_metadata``
    always merge-patches under a named platform section, so a top-level field
    needs a read-merge-write instead.
    """
    session = await db.get_session(session_id)
    assert session is not None
    merged = dict(session.origin_metadata)
    merged["user_id"] = user_id
    await db.update_session(session_id, origin_metadata=json.dumps(merged))


def _session(
    *,
    origin: str,
    discord_thread_id: int | None = None,
    telegram_user_id: int | None = None,
    system_role: str | None = None,
) -> Session:
    origin_metadata: dict[str, object] = {}  # guard: loose-dict - Session.origin_metadata JSON section
    if discord_thread_id is not None:
        origin_metadata["discord"] = {"thread_id": discord_thread_id}
    if telegram_user_id is not None:
        origin_metadata["user_id"] = telegram_user_id
    return Session(
        session_id="sess-routing",
        computer_name="local",
        tmux_session_name="tc-sess-routing",
        title="routing",
        last_input_origin=origin,
        origin_metadata=origin_metadata,
        system_role=system_role,
    )


async def test_dual_scope_delivers_to_origin_and_discord_admin_lane(
    monkeypatch: pytest.MonkeyPatch, cluster_event_bus: None
) -> None:
    """session-output-routing#delivery-scopes DUAL: origin + Discord admin copy."""
    del cluster_event_bus
    db = await _make_db()
    try:
        _patch_db(monkeypatch, db)
        session = _session(origin=InputOrigin.TELEGRAM.value, discord_thread_id=999, telegram_user_id=42)
        await db.create_session(
            computer_name=session.computer_name,
            tmux_session_name=session.tmux_session_name,
            last_input_origin=session.last_input_origin,
            title=session.title,
            session_id=session.session_id,
            emit_session_started=False,
        )
        await db.update_origin_metadata(session.session_id, "discord", {"thread_id": 999})
        await _set_telegram_user_id(db, session.session_id, 42)

        runtime = AdapterRuntime()
        telegram_fake = _RecordingUiAdapter(InputOrigin.TELEGRAM.value)
        discord_fake = _RecordingUiAdapter(InputOrigin.DISCORD.value)
        runtime.adapters[InputOrigin.TELEGRAM.value] = telegram_fake
        runtime.adapters[InputOrigin.DISCORD.value] = discord_fake

        await runtime.send_output_update(session, "hello", 0.0, 0.0)

        assert len(telegram_fake.sent) == 1
        assert telegram_fake.sent[0].platform == InputOrigin.TELEGRAM.value
        assert telegram_fake.sent[0].chat_id == 42
        assert len(discord_fake.sent) == 1
        assert discord_fake.sent[0].platform == InputOrigin.DISCORD.value
        assert discord_fake.sent[0].channel_id == 999
    finally:
        await db.close()


async def test_discord_origin_suppresses_duplicate_admin_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """session-output-routing#admin-output-lane-contract: origin==discord -> single delivery, no duplicate."""
    db = await _make_db()
    try:
        _patch_db(monkeypatch, db)
        session = _session(origin=InputOrigin.DISCORD.value, discord_thread_id=999)
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
        discord_fake = _RecordingUiAdapter(InputOrigin.DISCORD.value)
        runtime.adapters[InputOrigin.DISCORD.value] = discord_fake

        await runtime.send_output_update(session, "hello", 0.0, 0.0)

        assert len(discord_fake.sent) == 1
    finally:
        await db.close()


async def test_reflection_targets_discord_only_when_origin_not_discord(
    monkeypatch: pytest.MonkeyPatch, cluster_event_bus: None
) -> None:
    """session-output-routing#reflection-lane-contract: extra admin reflection is Discord-only."""
    del cluster_event_bus
    db = await _make_db()
    try:
        _patch_db(monkeypatch, db)
        session = _session(origin=InputOrigin.TELEGRAM.value, telegram_user_id=42)
        await db.create_session(
            computer_name=session.computer_name,
            tmux_session_name=session.tmux_session_name,
            last_input_origin=session.last_input_origin,
            title=session.title,
            session_id=session.session_id,
            emit_session_started=False,
        )
        await _set_telegram_user_id(db, session.session_id, 42)

        runtime = AdapterRuntime()
        telegram_fake = _RecordingUiAdapter(InputOrigin.TELEGRAM.value)
        discord_fake = _RecordingUiAdapter(InputOrigin.DISCORD.value)
        runtime.adapters[InputOrigin.TELEGRAM.value] = telegram_fake
        runtime.adapters[InputOrigin.DISCORD.value] = discord_fake

        await runtime.broadcast_user_input(session, "hi there", InputOrigin.TELEGRAM.value, actor_name="Tester")

        assert len(discord_fake.sent) == 1
        assert discord_fake.sent[0].platform == InputOrigin.DISCORD.value
        assert telegram_fake.sent == []
    finally:
        await db.close()


async def test_reflection_suppressed_for_discord_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """session-output-routing#reflection-lane-contract: origin==discord -> no duplicate reflection."""
    db = await _make_db()
    try:
        _patch_db(monkeypatch, db)
        session = _session(origin=InputOrigin.DISCORD.value, discord_thread_id=999)
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
        discord_fake = _RecordingUiAdapter(InputOrigin.DISCORD.value)
        runtime.adapters[InputOrigin.DISCORD.value] = discord_fake

        await runtime.broadcast_user_input(session, "hi there", InputOrigin.DISCORD.value, actor_name="Tester")

        assert discord_fake.sent == []
    finally:
        await db.close()


async def test_system_role_session_suppresses_discord_admin_copy(
    monkeypatch: pytest.MonkeyPatch, cluster_event_bus: None
) -> None:
    """session-output-routing#admin-output-lane-contract: system-role sessions skip the admin copy."""
    del cluster_event_bus
    db = await _make_db()
    try:
        _patch_db(monkeypatch, db)
        session = _session(
            origin=InputOrigin.TELEGRAM.value,
            telegram_user_id=42,
            system_role="integrator",
        )
        await db.create_session(
            computer_name=session.computer_name,
            tmux_session_name=session.tmux_session_name,
            last_input_origin=session.last_input_origin,
            title=session.title,
            session_id=session.session_id,
            system_role=session.system_role,
            emit_session_started=False,
        )
        await _set_telegram_user_id(db, session.session_id, 42)

        runtime = AdapterRuntime()
        telegram_fake = _RecordingUiAdapter(InputOrigin.TELEGRAM.value)
        discord_fake = _RecordingUiAdapter(InputOrigin.DISCORD.value)
        runtime.adapters[InputOrigin.TELEGRAM.value] = telegram_fake
        runtime.adapters[InputOrigin.DISCORD.value] = discord_fake

        await runtime.send_output_update(session, "hello", 0.0, 0.0)

        assert len(telegram_fake.sent) == 1
        assert discord_fake.sent == []
    finally:
        await db.close()


async def test_reconcile_final_output_repairs_telegram_origin_without_topic_id(
    monkeypatch: pytest.MonkeyPatch,
    cluster_event_bus: None,
) -> None:
    """session-output-routing final-output repair: Telegram origin viability follows chat_id, not topic_id."""
    del cluster_event_bus
    db = await _make_db()
    try:
        _patch_db(monkeypatch, db)
        session = _session(origin=InputOrigin.TELEGRAM.value, telegram_user_id=42)
        await db.create_session(
            computer_name=session.computer_name,
            tmux_session_name=session.tmux_session_name,
            last_input_origin=session.last_input_origin,
            title=session.title,
            session_id=session.session_id,
            emit_session_started=False,
        )
        await _set_telegram_user_id(db, session.session_id, 42)
        stop_at = datetime.now(UTC)
        await db.update_session(
            session.session_id,
            last_agent_stop_at=stop_at,
            last_output_raw="missed final output",
        )

        runtime = AdapterRuntime()
        telegram_fake = _RecordingUiAdapter(InputOrigin.TELEGRAM.value)
        runtime.adapters[InputOrigin.TELEGRAM.value] = telegram_fake

        repaired = await runtime.reconcile_outstanding_final_outputs(session.computer_name)

        assert repaired == 1
        assert len(telegram_fake.sent) == 1
        assert telegram_fake.sent[0].chat_id == 42
    finally:
        await db.close()


async def test_origin_only_scope_delivers_to_origin_adapter_only(
    monkeypatch: pytest.MonkeyPatch, cluster_event_bus: None
) -> None:
    """session-output-routing#delivery-scopes ORIGIN_ONLY: feedback/notice traffic never fans out to admin."""
    del cluster_event_bus
    db = await _make_db()
    try:
        _patch_db(monkeypatch, db)
        session = _session(origin=InputOrigin.TELEGRAM.value, telegram_user_id=42)
        await db.create_session(
            computer_name=session.computer_name,
            tmux_session_name=session.tmux_session_name,
            last_input_origin=session.last_input_origin,
            title=session.title,
            session_id=session.session_id,
            emit_session_started=False,
        )
        await _set_telegram_user_id(db, session.session_id, 42)

        runtime = AdapterRuntime()
        telegram_fake = _RecordingUiAdapter(InputOrigin.TELEGRAM.value)
        discord_fake = _RecordingUiAdapter(InputOrigin.DISCORD.value)
        runtime.adapters[InputOrigin.TELEGRAM.value] = telegram_fake
        runtime.adapters[InputOrigin.DISCORD.value] = discord_fake

        # Default cleanup_trigger=NEXT_NOTICE -> feedback=True -> source_only -> ORIGIN_ONLY shape.
        await runtime.send_message(session, "a feedback notice")

        assert len(telegram_fake.sent) == 1
        assert discord_fake.sent == []
    finally:
        await db.close()


async def test_ctrl_scope_status_dispatch_sends_no_message_content(
    monkeypatch: pytest.MonkeyPatch, cluster_event_bus: None
) -> None:
    """session-output-routing#delivery-scopes CTRL: internal control signals never fan out as UI content."""
    del cluster_event_bus
    db = await _make_db()
    try:
        _patch_db(monkeypatch, db)
        session = _session(origin=InputOrigin.TELEGRAM.value, telegram_user_id=42)
        await db.create_session(
            computer_name=session.computer_name,
            tmux_session_name=session.tmux_session_name,
            last_input_origin=session.last_input_origin,
            title=session.title,
            session_id=session.session_id,
            emit_session_started=False,
        )
        await _set_telegram_user_id(db, session.session_id, 42)

        runtime = AdapterRuntime()
        telegram_fake = _RecordingUiAdapter(InputOrigin.TELEGRAM.value)
        discord_fake = _RecordingUiAdapter(InputOrigin.DISCORD.value)
        runtime.adapters[InputOrigin.TELEGRAM.value] = telegram_fake
        runtime.adapters[InputOrigin.DISCORD.value] = discord_fake

        # "active" is a status/presence control signal (typing pulse only) — CTRL scope,
        # not user/admin UI message fan-out.
        await runtime.dispatch_session_status(session.session_id, "active")

        assert telegram_fake.sent == []
        assert discord_fake.sent == []
    finally:
        await db.close()


async def test_discord_metadata_channel_id_override_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """adapter-client Router invariant: metadata.channel_id overrides the session-derived Discord destination."""
    db = await _make_db()
    try:
        _patch_db(monkeypatch, db)
        session = _session(origin=InputOrigin.DISCORD.value, discord_thread_id=999)
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
        discord_fake = _RecordingUiAdapter(InputOrigin.DISCORD.value)
        runtime.adapters[InputOrigin.DISCORD.value] = discord_fake

        await runtime.send_message(session, "override target", metadata=MessageMetadata(channel_id="777"))

        assert len(discord_fake.sent) == 1
        assert discord_fake.sent[0].channel_id == 777
    finally:
        await db.close()


async def test_router_plan_message_intent_to_scope_mapping() -> None:
    """session-output-routing#message-intent-to-scope-mapping via the structured Router.plan() API."""
    router = Router(["discord", "telegram"])
    session = _session(origin=InputOrigin.TELEGRAM.value, discord_thread_id=999, telegram_user_id=42)

    origin_only = router.plan(session, "feedback_notice_error_status")
    assert origin_only.scope is DeliveryScope.ORIGIN_ONLY
    assert origin_only.origin_endpoint is not None
    assert origin_only.origin_endpoint.platform == InputOrigin.TELEGRAM.value
    assert origin_only.admin_lane_destinations == ()

    admin_only = router.plan(session, "input_reflection_text")
    assert admin_only.scope is DeliveryScope.ADMIN_ONLY
    assert admin_only.origin_endpoint is None
    assert len(admin_only.admin_lane_destinations) == 1
    assert admin_only.admin_lane_destinations[0].platform == InputOrigin.DISCORD.value

    dual = router.plan(session, "output_stream_chunk_final_threaded")
    assert dual.scope is DeliveryScope.DUAL
    assert dual.origin_endpoint is not None
    assert len(dual.admin_lane_destinations) == 1

    ctrl = router.plan(session, "ctrl_activity")
    assert ctrl.scope is DeliveryScope.CTRL
    assert ctrl.origin_endpoint is None
    assert ctrl.admin_lane_destinations == ()


async def test_router_plan_discord_origin_has_no_admin_lane_in_dual_scope() -> None:
    """session-output-routing#admin-output-lane-contract via Router.plan(): discord origin -> no admin lane."""
    router = Router(["discord", "telegram"])
    session = _session(origin=InputOrigin.DISCORD.value, discord_thread_id=999)

    dual = router.plan(session, "output_stream_chunk_final_threaded")
    assert dual.scope is DeliveryScope.DUAL
    assert dual.origin_endpoint is not None
    assert dual.origin_endpoint.platform == InputOrigin.DISCORD.value
    assert dual.admin_lane_destinations == ()
