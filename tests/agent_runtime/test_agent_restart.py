"""Functional coverage for self-restart continuation-stimulus delivery.

Drives the real restart surface (`CommandService.restart_agent`) with only the
tmux/process boundary faked, and asserts on tmux delivery actions and emitted
events — never on logger output. Prompt-state delivery is successful when the
live prompt accepts Enter; `user_prompt_submit` is only an opportunistic later
signal while delivery is still observing.
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
from teleclaude.core.agents import AgentName
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
_LIVE_STIMULUS_PROMPT = f"{AgentName.CLAUDE.prompt_marker} {RESTART_CONTINUATION_STIMULUS}"


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


def _stimulus_paste_count(paste_recorder: AsyncMock) -> int:
    return sum(1 for call in paste_recorder.await_args_list if call.kwargs.get("text") == RESTART_CONTINUATION_STIMULUS)


async def _prepare_restart(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    pane_output: str | list[str] = _LIVE_STIMULUS_PROMPT,
    submit_delays: tuple[float, ...] = (0.2, 0.05, 0.05),
) -> tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock, list, list]:
    """Wire the faked tmux/process boundary and a restart-eligible session.

    Returns tmux action recorders plus the emitted events the tests assert on.
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
    paste_recorder = AsyncMock(return_value=True)
    enter_recorder = AsyncMock(return_value=True)
    ctrl_recorder = AsyncMock(return_value=True)
    pane_outputs = [pane_output] if isinstance(pane_output, str) else list(pane_output)

    async def _capture_pane(_tmux_session_name: str | None) -> str:
        if len(pane_outputs) == 3:
            if paste_recorder.await_count == 0:
                return pane_outputs[0]
            if enter_recorder.await_count == 0:
                return pane_outputs[1]
            return pane_outputs[2]
        if len(pane_outputs) > 1:
            return pane_outputs.pop(0)
        return pane_outputs[0]

    monkeypatch.setattr(tmux_bridge, "send_keys_existing_tmux", send_recorder)
    monkeypatch.setattr(tmux_bridge, "paste_text_existing_tmux", paste_recorder)
    monkeypatch.setattr(tmux_bridge, "send_enter", enter_recorder)
    monkeypatch.setattr(tmux_bridge, "capture_pane", AsyncMock(side_effect=_capture_pane))
    monkeypatch.setattr(tmux_bridge, "send_ctrl_key", ctrl_recorder)
    monkeypatch.setattr(tmux_bridge, "wait_for_shell_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_bridge, "is_process_running", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_io, "INJECT_TURN_START_TIMEOUT_S", 0.05)
    monkeypatch.setattr(tmux_io, "INJECT_PASTE_VISIBLE_TIMEOUT_S", 0.05)
    monkeypatch.setattr(tmux_io, "INJECT_PROMPT_OBSERVE_INTERVAL_S", 0.01)
    monkeypatch.setattr(tmux_io, "INJECT_SUBMIT_RETRY_DELAYS_S", submit_delays)

    timeout_events: list[SessionLifecycleContext] = []
    activity_events: list[UserPromptSubmitActivityEvent] = []

    async def _record_timeout(_event: str, ctx: SessionLifecycleContext) -> None:
        timeout_events.append(ctx)

    async def _record_activity(_event: str, ctx: UserPromptSubmitActivityEvent) -> None:
        activity_events.append(ctx)

    event_bus.subscribe(TeleClaudeEvents.AGENT_READINESS_TIMEOUT, _record_timeout)
    event_bus.subscribe(TeleClaudeEvents.AGENT_ACTIVITY, _record_activity)

    return send_recorder, paste_recorder, enter_recorder, ctrl_recorder, timeout_events, activity_events


def _stale_claude_collapsed_paste_prompt() -> str:
    return f"""
 ▐▛███▜▌   Claude Code v2.1.193
────────────────────────────────────────────────────────────────
{AgentName.CLAUDE.prompt_marker} /next-prepare stale-work

  ADDITIONAL CONTEXT:
  human_in_loop: false
  [Pasted text #2 +4 lines]
────────────────────────────────────────────────────────────────
  Model: Opus 4.8
"""


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
async def test_self_restart_reports_stimulus_delivered_when_prompt_state_clears(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prompt-state transition delivers the stimulus once, with no hook dependency."""
    (
        _send_recorder,
        paste_recorder,
        enter_recorder,
        ctrl_recorder,
        timeout_events,
        activity_events,
    ) = await _prepare_restart(
        api,
        monkeypatch,
        pane_output=[
            f"{AgentName.CLAUDE.prompt_marker} ",
            _LIVE_STIMULUS_PROMPT,
            f"{AgentName.CLAUDE.prompt_marker} ",
        ],
    )

    ok, _err = await get_command_service().restart_agent(RestartAgentCommand(session_id=_SESSION_ID, self_restart=True))
    assert ok is True

    await _emit_ready()
    assert await _wait_until(lambda: _stimulus_paste_count(paste_recorder) >= 1 and enter_recorder.await_count >= 1)
    await _await_inject_task()

    assert _stimulus_paste_count(paste_recorder) == 1
    assert enter_recorder.await_count == 1
    assert ctrl_recorder.await_count == 0
    assert activity_events == []
    assert timeout_events == []


@pytest.mark.spec(_SPEC, "UC-AR2")
async def test_self_restart_retries_enter_while_prompt_state_remains_occupied(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stuck live prompt retries Enter without re-pasting the stimulus."""
    (
        _send_recorder,
        paste_recorder,
        enter_recorder,
        ctrl_recorder,
        timeout_events,
        activity_events,
    ) = await _prepare_restart(api, monkeypatch)

    ok, _err = await get_command_service().restart_agent(RestartAgentCommand(session_id=_SESSION_ID, self_restart=True))
    assert ok is True

    await _emit_ready()
    assert await _wait_until(lambda: enter_recorder.await_count >= 2)
    await _emit_turn_start()
    await _await_inject_task()

    assert _stimulus_paste_count(paste_recorder) == 1
    assert enter_recorder.await_count == 2
    assert ctrl_recorder.await_count == 0
    assert len(activity_events) == 1  # exactly one turn ultimately starts — no double-start
    assert timeout_events == []


@pytest.mark.spec(_SPEC, "UC-AR3")
async def test_self_restart_swallowed_input_fails_loud_without_success(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale collapsed paste prompt is never accepted as the live stimulus."""
    (
        _send_recorder,
        paste_recorder,
        enter_recorder,
        ctrl_recorder,
        timeout_events,
        activity_events,
    ) = await _prepare_restart(api, monkeypatch, pane_output=_stale_claude_collapsed_paste_prompt())

    ok, _err = await get_command_service().restart_agent(RestartAgentCommand(session_id=_SESSION_ID, self_restart=True))
    assert ok is True

    await _emit_ready()
    # Never emit a turn-start signal: the visible live prompt belongs to a different payload.
    await _await_inject_task()

    assert _stimulus_paste_count(paste_recorder) == 1  # never corrupts the buffer by re-pasting
    assert enter_recorder.await_count == 0  # never submit text that was not observed
    assert ctrl_recorder.await_count == 0
    assert activity_events == []  # no turn ever started
    assert len(timeout_events) == 1  # failure boundary reported, not silent
    svc = get_command_service()
    assert svc.client.send_message.await_count >= 1  # session kept alive with a message
