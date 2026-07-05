"""Functional coverage for restart continuation-stimulus delivery.

Drives the real restart surface (`CommandService.restart_agent`) with only the
tmux/process boundary faked, and asserts on tmux delivery actions and emitted
events — never on logger output. Prompt-state delivery is successful when the
live prompt accepts Enter; `user_prompt_submit` is only an opportunistic later
signal while delivery is still observing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import cast
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

import teleclaude.core.command_handlers._utils as utils_mod
import teleclaude.services.maintenance_service as maintenance_service_mod
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
from teleclaude.core.output_poller import OutputPoller
from teleclaude.events.envelope import EventVisibility
from teleclaude.services.maintenance_service import MaintenanceService
from teleclaude.types.commands import RestartAgentCommand

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/agent_runtime/agent-restart"
_DOMAIN_SPEC = "project/spec/domain/agent_runtime"
_SESSION_ID = "restart-uc-ar1"
_TMUX = "tc-restart-uc-ar1"


def _live_stimulus_prompt(agent: AgentName) -> str:
    return f"{agent.prompt_marker.strip()} {RESTART_CONTINUATION_STIMULUS}"


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
    active_agent: AgentName = AgentName.CLAUDE,
    pane_output: str | list[str] | None = None,
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
        active_agent=active_agent.value,
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
    resolved_pane_output = pane_output if pane_output is not None else _live_stimulus_prompt(active_agent)
    pane_outputs = [resolved_pane_output] if isinstance(resolved_pane_output, str) else list(resolved_pane_output)

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


def _stale_claude_suggestion_prompt() -> str:
    return f"""
 ▐▛███▜▌   Claude Code v2.1.193
────────────────────────────────────────────────────────────────
{AgentName.CLAUDE.prompt_marker} \x1b[2mTry "create a util logging.py that..."
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
            _live_stimulus_prompt(AgentName.CLAUDE),
            f"{AgentName.CLAUDE.prompt_marker} ",
        ],
    )
    wait_for_shell_ready = AsyncMock(
        side_effect=lambda _tmux, *, timeout_s=8.0, poll_interval_s=0.2: timeout_s > 8.0 and poll_interval_s == 1.0
    )
    monkeypatch.setattr(tmux_bridge, "wait_for_shell_ready", wait_for_shell_ready)

    ok, _err = await get_command_service().restart_agent(RestartAgentCommand(session_id=_SESSION_ID, self_restart=True))
    assert ok is True
    wait_for_shell_ready.assert_awaited_once()

    await _emit_ready()
    assert await _wait_until(lambda: _stimulus_paste_count(paste_recorder) >= 1 and enter_recorder.await_count >= 1)
    await _await_inject_task()

    assert _stimulus_paste_count(paste_recorder) == 1
    assert enter_recorder.await_count == 1
    assert ctrl_recorder.await_count == 0
    assert activity_events == []
    assert timeout_events == []


@pytest.mark.spec(_SPEC, "UC-AR1")
async def test_self_restart_reports_codex_stimulus_delivered_when_prompt_state_clears(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Codex prompt-state transition delivers the stimulus once."""
    del cluster_event_bus
    prompt_marker = AgentName.CODEX.prompt_marker.strip()
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
        active_agent=AgentName.CODEX,
        pane_output=[
            f"{prompt_marker} \n\n  gpt-5.5 high · ~/Workspace/InstruktAI/TeleClaude · main",
            "\n".join(
                [
                    _live_stimulus_prompt(AgentName.CODEX),
                    "",
                    "  gpt-5.5 high · ~/Workspace/InstruktAI/TeleClaude · main",
                ]
            ),
            f"{prompt_marker} \n\n  gpt-5.5 high · ~/Workspace/InstruktAI/TeleClaude · main",
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


@pytest.mark.spec(_DOMAIN_SPEC, "UC-ART-5")
async def test_maintenance_restore_reports_codex_stimulus_delivered_through_prompt_state(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Maintenance restore uses confirmed prompt-state delivery for the stimulus."""
    del cluster_event_bus
    monkeypatch.setattr(maintenance_service_mod, "db", api.db)

    await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name=_TMUX,
        last_input_origin="terminal",
        title="restore",
        session_id=_SESSION_ID,
        active_agent=AgentName.CODEX.value,
        thinking_mode="slow",
        native_session_id="native-abc",
        lifecycle_status="active",
        project_path="/tmp",
        emit_session_started=False,
    )
    session = await api.db.get_session(_SESSION_ID)
    assert session is not None

    prompt_marker = AgentName.CODEX.prompt_marker.strip()
    pane_outputs = [
        f"{prompt_marker} \n\n  gpt-5.5 high · ~/Workspace/InstruktAI/TeleClaude · main",
        "\n".join(
            [
                _live_stimulus_prompt(AgentName.CODEX),
                "",
                "  gpt-5.5 high · ~/Workspace/InstruktAI/TeleClaude · main",
            ]
        ),
        f"{prompt_marker} \n\n  gpt-5.5 high · ~/Workspace/InstruktAI/TeleClaude · main",
    ]

    async def _capture_pane(_tmux_session_name: str | None) -> str:
        if paste_recorder.await_count == 0:
            return pane_outputs[0]
        if enter_recorder.await_count == 0:
            return pane_outputs[1]
        return pane_outputs[2]

    send_recorder = AsyncMock()

    async def _send_keys_existing_tmux(*_args: object, **_kwargs: object) -> bool:
        await _emit_ready()
        return True

    send_recorder.side_effect = _send_keys_existing_tmux
    paste_recorder = AsyncMock(return_value=True)
    enter_recorder = AsyncMock(return_value=True)

    monkeypatch.setattr(tmux_bridge, "session_exists", AsyncMock(return_value=False))
    monkeypatch.setattr(maintenance_service_mod, "ensure_tmux_with_identity", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_bridge, "send_keys_existing_tmux", send_recorder)
    monkeypatch.setattr(tmux_bridge, "paste_text_existing_tmux", paste_recorder)
    monkeypatch.setattr(tmux_bridge, "send_enter", enter_recorder)
    monkeypatch.setattr(tmux_bridge, "capture_pane", AsyncMock(side_effect=_capture_pane))
    monkeypatch.setattr(tmux_io, "INJECT_PASTE_VISIBLE_TIMEOUT_S", 0.05)
    monkeypatch.setattr(tmux_io, "INJECT_PROMPT_OBSERVE_INTERVAL_S", 0.01)
    monkeypatch.setattr(tmux_io, "INJECT_SUBMIT_RETRY_DELAYS_S", (0.05, 0.05, 0.05))

    service = MaintenanceService(
        client=get_command_service().client,
        output_poller=cast(OutputPoller, AsyncMock()),
        poller_watch_interval_s=1.0,
    )
    await service._restore_tmux_session(session)  # pyright: ignore[reportPrivateUsage]

    assert send_recorder.await_count == 1
    assert all(call.kwargs.get("text") != RESTART_CONTINUATION_STIMULUS for call in send_recorder.await_args_list)
    assert _stimulus_paste_count(paste_recorder) == 1
    assert enter_recorder.await_count == 1


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
    """Suggestion chrome is never accepted as the live stimulus."""
    (
        _send_recorder,
        paste_recorder,
        enter_recorder,
        ctrl_recorder,
        timeout_events,
        activity_events,
    ) = await _prepare_restart(api, monkeypatch, pane_output=_stale_claude_suggestion_prompt())
    monkeypatch.setattr(tmux_io, "INJECT_PASTE_LANDED_TIMEOUT_S", 0.05)

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
