"""Functional regressions for session subscription turn dedup semantics."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

import teleclaude.core.agent_coordinator._coordinator as coordinator_mod
import teleclaude.core.agent_coordinator._fanout as fanout_mod
import teleclaude.core.db as db_mod
import teleclaude.core.db._sessions as db_sessions_mod
import teleclaude.core.polling_coordinator as polling_coordinator_mod
import teleclaude.core.session_listeners as listeners_mod
import teleclaude.core.tmux_delivery as tmux_delivery_mod
import teleclaude.hooks.receiver as receiver_mod
from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.db import Db
from teleclaude.core.db.connection_factory import get_outbox_db_path
from teleclaude.core.db_models import HookOutbox
from teleclaude.core.events import AgentEventContext, AgentHookEvents, build_agent_payload
from teleclaude.core.origins import InputOrigin

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/agent_runtime/session-subscriptions"


async def _install_runtime_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Db:
    runtime_db = Db(str(tmp_path / "runtime.db"))
    await runtime_db.initialize()
    monkeypatch.setattr(db_sessions_mod.event_bus, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(db_mod, "db", runtime_db)
    monkeypatch.setattr(coordinator_mod, "db", runtime_db)
    monkeypatch.setattr(fanout_mod, "db", runtime_db)
    monkeypatch.setattr(listeners_mod, "db", runtime_db)
    monkeypatch.setattr(polling_coordinator_mod, "db", runtime_db)
    monkeypatch.setattr(
        polling_coordinator_mod,
        "schedule_session_projection",
        AsyncMock(return_value=None),
    )
    return runtime_db


async def _create_runtime_session(runtime_db: Db, session_id: str, *, tmux_name: str) -> None:
    await runtime_db.create_session(
        computer_name="local",
        tmux_session_name=tmux_name,
        last_input_origin=InputOrigin.TERMINAL.value,
        title=session_id,
        session_id=session_id,
        active_agent="claude",
        emit_session_started=False,
    )


def _run_receiver_for_prompt(
    monkeypatch: pytest.MonkeyPatch,
    *,
    outbox_db: str,
    session_id: str,
    prompt: str,
) -> None:
    monkeypatch.setattr(receiver_mod, "_get_default_outbox_db", lambda: outbox_db)
    monkeypatch.setattr(receiver_mod, "_resolve_receiver_session_id", lambda *args: session_id)
    monkeypatch.setattr(sys, "argv", ["receiver", "--agent", "claude", "UserPromptSubmit"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": prompt})))
    receiver_mod.main()


def _read_outbox_rows(outbox_db: str) -> list[HookOutbox]:
    with receiver_mod.get_outbox_session(outbox_db) as session:
        return list(session.exec(select(HookOutbox).order_by(HookOutbox.id)).all())


@pytest.mark.spec(_SPEC, "UC-SS1")
async def test_orchestrator_repoke_clears_dedup_flag_and_renotifies_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_db = await _install_runtime_db(monkeypatch, tmp_path)
    await _create_runtime_session(runtime_db, "target-session", tmux_name="target-pane")
    await _create_runtime_session(runtime_db, "caller-session", tmux_name="caller-pane")
    await runtime_db.register_listener(
        target_session_id="target-session",
        caller_session_id="caller-session",
        caller_tmux_session="caller-pane",
    )
    await runtime_db.set_notification_flag("target-session", True)

    outbox_db = str(get_outbox_db_path(tmp_path))
    _run_receiver_for_prompt(
        monkeypatch,
        outbox_db=outbox_db,
        session_id="target-session",
        prompt="[Orchestrator (caller-session) on local]\n\nContinue.",
    )
    rows = _read_outbox_rows(outbox_db)

    assert len(rows) == 1
    assert rows[0].event_type == AgentHookEvents.USER_PROMPT_SUBMIT

    payload = build_agent_payload(AgentHookEvents.USER_PROMPT_SUBMIT, json.loads(rows[0].payload))
    coordinator = AgentCoordinator(
        client=SimpleNamespace(break_threaded_turn=AsyncMock()),
        tts_manager=SimpleNamespace(speak=AsyncMock()),
    )
    await coordinator.handle_user_prompt_submit(
        AgentEventContext(
            session_id="target-session",
            data=payload,
            event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
        )
    )
    assert await runtime_db.get_notification_flag("target-session") is False

    send_keys = AsyncMock(return_value=True)
    monkeypatch.setattr(tmux_delivery_mod.tmux_bridge, "send_keys_existing_tmux", send_keys)
    await coordinator._notify_session_listener("target-session")
    await coordinator._notify_session_listener("target-session")

    assert send_keys.await_count == 1
    assert await runtime_db.get_notification_flag("target-session") is True


@pytest.mark.spec(_SPEC, "UC-SS2")
async def test_hook_side_channel_prompt_keeps_dedup_flag_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_db = await _install_runtime_db(monkeypatch, tmp_path)
    await _create_runtime_session(runtime_db, "target-session", tmux_name="target-pane")
    await runtime_db.set_notification_flag("target-session", True)

    outbox_db = str(get_outbox_db_path(tmp_path))
    _run_receiver_for_prompt(
        monkeypatch,
        outbox_db=outbox_db,
        session_id="target-session",
        prompt="[TeleClaude Checkpoint] - Stop hook feedback",
    )

    rows = _read_outbox_rows(outbox_db)
    assert rows == []
    assert await runtime_db.get_notification_flag("target-session") is True

    send_keys = AsyncMock(return_value=True)
    monkeypatch.setattr(tmux_delivery_mod.tmux_bridge, "send_keys_existing_tmux", send_keys)
    coordinator = AgentCoordinator(
        client=SimpleNamespace(break_threaded_turn=AsyncMock()),
        tts_manager=SimpleNamespace(speak=AsyncMock()),
    )
    await coordinator._notify_session_listener("target-session")

    assert send_keys.await_count == 0
