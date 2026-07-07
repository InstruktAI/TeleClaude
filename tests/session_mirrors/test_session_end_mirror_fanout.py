"""Functional binding for local agent-stop reaching the mirror fanout."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import teleclaude.daemon_hook_outbox as daemon_hook_outbox_mod
import teleclaude.mirrors.processors as processors_mod
from teleclaude.core.agents import AgentName
from teleclaude.core.db import Db
from teleclaude.core.events import AgentHookEvents
from teleclaude.core.origins import InputOrigin
from teleclaude.daemon_hook_outbox import _DaemonHookOutboxMixin
from teleclaude.daemon_session import _DaemonSessionMixin
from teleclaude.mirrors.processors import MirrorEvent

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/session_mirrors/session-end-mirror-fanout"
_SESSION_ID = "target-session"
_TRANSCRIPT_PATH = "/tmp/transcript.jsonl"


class _FanoutDaemon(_DaemonHookOutboxMixin, _DaemonSessionMixin):
    """Minimal composition of the mixins under test — mirrors TeleClaudeDaemon's MRO."""

    def __init__(self) -> None:
        self.agent_coordinator = SimpleNamespace(handle_event=AsyncMock())


async def _install_runtime_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Db:
    runtime_db = Db(str(tmp_path / "runtime.db"))
    await runtime_db.initialize()
    monkeypatch.setattr(daemon_hook_outbox_mod, "db", runtime_db)
    return runtime_db


async def _create_session(runtime_db: Db, session_id: str) -> None:
    await runtime_db.create_session(
        computer_name="local",
        tmux_session_name="",
        last_input_origin=InputOrigin.TERMINAL.value,
        title=session_id,
        session_id=session_id,
        active_agent=AgentName.CLAUDE.value,
        emit_session_started=False,
    )


@pytest.mark.spec(_SPEC, "UC-SEMF-1")
async def test_local_agent_stop_reaches_mirror_fanout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_db = await _install_runtime_db(monkeypatch, tmp_path)
    await _create_session(runtime_db, _SESSION_ID)

    monkeypatch.setattr(processors_mod, "_processors", [])
    captured: list[MirrorEvent] = []

    async def _spy(event: MirrorEvent) -> None:
        captured.append(event)

    processors_mod.register_processor(_spy)

    daemon = _FanoutDaemon()
    await daemon._dispatch_hook_event(
        _SESSION_ID,
        AgentHookEvents.AGENT_STOP,
        {"transcript_path": _TRANSCRIPT_PATH, "agent_name": AgentName.CLAUDE.value},
    )

    assert daemon.agent_coordinator.handle_event.await_count == 1
    assert len(captured) == 1
    assert captured[0].session_id == _SESSION_ID
    assert captured[0].transcript_path == _TRANSCRIPT_PATH


@pytest.mark.spec(_SPEC, "UC-SEMF-1")
async def test_non_stop_agent_event_does_not_reach_mirror_fanout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_db = await _install_runtime_db(monkeypatch, tmp_path)
    await _create_session(runtime_db, _SESSION_ID)

    monkeypatch.setattr(processors_mod, "_processors", [])
    captured: list[MirrorEvent] = []

    async def _spy(event: MirrorEvent) -> None:
        captured.append(event)

    processors_mod.register_processor(_spy)

    daemon = _FanoutDaemon()
    await daemon._dispatch_hook_event(
        _SESSION_ID,
        AgentHookEvents.TOOL_USE,
        {"transcript_path": _TRANSCRIPT_PATH, "agent_name": AgentName.CLAUDE.value},
    )

    assert daemon.agent_coordinator.handle_event.await_count == 1
    assert captured == []
