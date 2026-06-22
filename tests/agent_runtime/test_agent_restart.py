"""Functional coverage for self-restart continuation-stimulus delivery (UC-AR1).

Drives the real restart surface (`CommandService.restart_agent`) with only the
tmux/process boundary faked, and asserts on the tmux send recorder and emitted
events — never on logger output or internal helpers. The positive turn-start
signal is the `user_prompt_submit` agent-activity event the runtime already emits
when an agent accepts a turn.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

import teleclaude.core.command_handlers._utils as utils_mod
from teleclaude.constants import RESTART_CONTINUATION_STIMULUS
from teleclaude.core import tmux_bridge, tmux_io
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentHookEvents,
    SessionLifecycleContext,
    TeleClaudeEvents,
    UserPromptSubmitActivityEvent,
)
from teleclaude.events.envelope import EventVisibility
from teleclaude.types.commands import RestartAgentCommand

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/agent_runtime/agent-restart"
_SESSION_ID = "restart-uc-ar1"
_TMUX = "tc-restart-uc-ar1"


async def _wait_until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> bool:
    """Poll ``predicate`` cooperatively until true or the timeout elapses."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


async def _await_inject_task(*, timeout: float = 5.0) -> None:
    """Await the fire-and-forget continuation-stimulus task to completion."""
    tasks = [t for t in asyncio.all_tasks() if t.get_name() == "send-restart-stimulus"]
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)


def _stimulus_send_count(send_recorder: AsyncMock) -> int:
    return sum(1 for call in send_recorder.await_args_list if call.kwargs.get("text") == RESTART_CONTINUATION_STIMULUS)


async def _prepare_restart(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[AsyncMock, AsyncMock, list, list]:
    """Wire the faked tmux/process boundary and a restart-eligible session.

    Returns the (send recorder, ctrl-key recorder, readiness-timeout events,
    activity events) handles the tests assert on.
    """
    # with_session resolves the session through _utils.db, which the api fixture
    # does not re-bind to the in-memory test DB.
    monkeypatch.setattr(utils_mod, "db", api.db)

    await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name=_TMUX,
        last_input_origin="terminal",
        title="restart",
        session_id=_SESSION_ID,
        active_agent="claude",
        thinking_mode="slow",
        native_session_id="native-abc",
        lifecycle_status="active",
        emit_session_started=False,
    )

    svc = get_command_service()
    # The stub adapter client lacks the attribute the real AdapterClient carries.
    svc.client.agent_coordinator = None

    send_recorder = AsyncMock(return_value=True)
    ctrl_recorder = AsyncMock(return_value=True)
    monkeypatch.setattr(tmux_bridge, "send_keys_existing_tmux", send_recorder)
    monkeypatch.setattr(tmux_bridge, "send_ctrl_key", ctrl_recorder)
    monkeypatch.setattr(tmux_bridge, "wait_for_shell_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_bridge, "is_process_running", AsyncMock(return_value=True))

    timeout_events: list[SessionLifecycleContext] = []
    activity_events: list[UserPromptSubmitActivityEvent] = []

    async def _record_timeout(_event: str, ctx: SessionLifecycleContext) -> None:
        timeout_events.append(ctx)

    async def _record_activity(_event: str, ctx: UserPromptSubmitActivityEvent) -> None:
        activity_events.append(ctx)

    event_bus.subscribe(TeleClaudeEvents.AGENT_READINESS_TIMEOUT, _record_timeout)
    event_bus.subscribe(TeleClaudeEvents.AGENT_ACTIVITY, _record_activity)

    return send_recorder, ctrl_recorder, timeout_events, activity_events


async def _emit_ready() -> None:
    await event_bus.emit(
        TeleClaudeEvents.AGENT_READY,
        SessionLifecycleContext(session_id=_SESSION_ID),
        visibility=EventVisibility.LOCAL,
    )


async def _emit_turn_start() -> None:
    await event_bus.emit(
        TeleClaudeEvents.AGENT_ACTIVITY,
        UserPromptSubmitActivityEvent(
            session_id=_SESSION_ID,
            event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
        ),
        visibility=EventVisibility.LOCAL,
    )


@pytest.mark.spec(_SPEC, "UC-AR1")
async def test_self_restart_delivers_stimulus_on_confirmed_turn_start(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A confirmed turn start delivers the stimulus once, with no re-inject."""
    send_recorder, ctrl_recorder, timeout_events, activity_events = await _prepare_restart(api, monkeypatch)

    ok, _err = await get_command_service().restart_agent(RestartAgentCommand(session_id=_SESSION_ID, self_restart=True))
    assert ok is True

    await _emit_ready()
    assert await _wait_until(lambda: _stimulus_send_count(send_recorder) >= 1)
    await _emit_turn_start()
    await _await_inject_task()

    assert _stimulus_send_count(send_recorder) == 1
    assert ctrl_recorder.await_count == 0  # no re-inject
    assert len(activity_events) == 1  # exactly one turn started
    assert timeout_events == []  # no failure boundary


@pytest.mark.spec(_SPEC, "UC-AR2")
async def test_self_restart_reinjects_when_turn_start_is_deferred(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deferred turn start triggers an idempotent re-inject, one turn total."""
    monkeypatch.setattr(tmux_io, "INJECT_TURN_START_TIMEOUT_S", 0.2)
    send_recorder, ctrl_recorder, timeout_events, activity_events = await _prepare_restart(api, monkeypatch)

    ok, _err = await get_command_service().restart_agent(RestartAgentCommand(session_id=_SESSION_ID, self_restart=True))
    assert ok is True

    await _emit_ready()
    # First attempt's paste lands but no turn starts; wait for the re-inject
    # (input-line clear + second paste) before delivering the turn-start signal.
    assert await _wait_until(lambda: ctrl_recorder.await_count >= 1 and _stimulus_send_count(send_recorder) >= 2)
    await _emit_turn_start()
    await _await_inject_task()

    assert _stimulus_send_count(send_recorder) == 2
    assert ctrl_recorder.await_count == 1  # cleared the input line once before re-paste
    assert len(activity_events) == 1  # exactly one turn ultimately starts — no double-start
    assert timeout_events == []


@pytest.mark.spec(_SPEC, "UC-AR3")
async def test_self_restart_swallowed_input_fails_loud_without_success(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A swallowed paste (no turn start ever) is never reported as delivered."""
    monkeypatch.setattr(tmux_io, "INJECT_TURN_START_TIMEOUT_S", 0.1)
    monkeypatch.setattr(tmux_io, "INJECT_MAX_ATTEMPTS", 3)
    send_recorder, ctrl_recorder, timeout_events, activity_events = await _prepare_restart(api, monkeypatch)

    ok, _err = await get_command_service().restart_agent(RestartAgentCommand(session_id=_SESSION_ID, self_restart=True))
    assert ok is True

    await _emit_ready()
    # Never emit a turn-start signal: every paste is swallowed.
    await _await_inject_task()

    assert _stimulus_send_count(send_recorder) == 3  # exhausted the retry cap
    assert ctrl_recorder.await_count == 2  # re-cleared the line before each retry
    assert activity_events == []  # no turn ever started
    assert len(timeout_events) == 1  # failure boundary reported, not silent
    svc = get_command_service()
    assert svc.client.send_message.await_count >= 1  # session kept alive with a message
