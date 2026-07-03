"""Functional tests for session identity and human_role behavior.

These tests act as an agent would: create sessions via the real API,
receive tokens, and use those tokens to call further API endpoints.
The full auth stack runs — verify_caller, role clearance, token issuance.
No fallback to admin should exist for sessions without explicit identity.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict, cast
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient, Response

import teleclaude.core.agent_coordinator._coordinator as coordinator_mod
import teleclaude.core.command_handlers._agent as agent_handler_mod
import teleclaude.core.command_handlers._utils as command_utils_mod
import teleclaude.core.session_bootstrap as session_bootstrap_mod
import teleclaude.core.session_listeners as session_listeners_mod
import teleclaude.daemon_session as daemon_session_mod
from teleclaude.api import auth as auth_mod
from teleclaude.api import sessions_actions_routes, sessions_routes
from teleclaude.api.session_ownership import LocalOwnership, RemoteOwnership, resolve_session_ownership
from teleclaude.cli import api_client as api_client_mod
from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.cli.tool_commands import sessions as sessions_tool
from teleclaude.constants import (
    ROLE_ORCHESTRATOR,
    ROLE_WORKER,
    WORKTREE_DIR,
    JobRole,
    ResultStatus,
    SlashCommand,
)
from teleclaude.core import command_dispatch as command_dispatch_mod
from teleclaude.core import tmux_bridge, tmux_io
from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.agents import AgentName
from teleclaude.core.command_dispatch import RemoteDispatchError, forward_command_to_peer
from teleclaude.core.command_handlers import _session as session_handler_mod
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.command_service import CommandService
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    SessionLifecycleContext,
    TeleClaudeEvents,
    UserPromptSubmitActivityEvent,
    build_agent_payload,
)
from teleclaude.core.identity import IdentityContext
from teleclaude.core.models import JsonDict, MessageMetadata, SessionLaunchIntent, SessionSnapshot
from teleclaude.core.models._session import Session
from teleclaude.core.next_machine.manual_start import adopt_manual_lifecycle_session
from teleclaude.core.next_machine.runner_types import ManualLifecycleStatus
from teleclaude.core.next_machine.runtime.sessions import find_live_session_for_slug
from teleclaude.core.operation_caller_identity import reset_caller_session_id, set_caller_session_id
from teleclaude.core.origins import InputOrigin
from teleclaude.core.todos_db import get_todos_db
from teleclaude.events.envelope import EventVisibility
from teleclaude.project_root import resolve_state_root
from teleclaude.transport.redis_transport import _messaging as redis_messaging_mod
from teleclaude.transport.redis_transport._messaging import _MessagingMixin
from teleclaude.types.commands import (
    CloseSessionCommand,
    CreateSessionCommand,
    KeysCommand,
    RestartAgentCommand,
    UnsubscribeSessionCommand,
)
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todos import TodoState

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/agent_runtime/session-lifecycle"
_ACCEPTED_STATUS = "accepted"
_CALLER_SESSION_ID = "caller-session"
_CREATED_SESSION_ID = "created-session"
_FIRE_AND_FORGET_RESPONSE_MODE = "fire_and_forget"
_HELLO_TEXT = "hello"
_IMMEDIATE_RESPONSE_MODE = "immediate"
_KEY_ENTER = "enter"
_MESSAGE_ID = "message-1"
_PEER_COMPUTER = "PeerComputer"
_PEER_RESTART_FAILURE = "peer restart failed"
_PROJECT_PATH = "/tmp/project"
_RESTART_FAILURE = "restart failed"
_SESSION_ID = "session-1"
_SUCCESS_STATUS = "success"
_TARGET_SESSION_ID = "target-session"
_TERMINAL_ORIGIN = "terminal"
_TMUX_CREATED_SESSION = "tc-created-session"


class _RemoteDispatchRecord(TypedDict):
    computer: str
    command: str
    session_id: str | None
    command_payload: JsonDict | None


class _RemoteReadRecord(TypedDict):
    message_id: str
    target_computer: str | None
    timeout: float


class _SessionMessagesRpcCapture(TypedDict):
    session_id: str
    recipient_email: str | None
    recipient_role: str | None
    since: str | None
    include_tools: bool | None
    include_thinking: bool
    tail_chars: int
    tail_scope: str


class _CreateSessionResponse(TypedDict):
    status: str
    session_id: str
    tmux_session_name: str
    agent: str | None


class _RemoteDispatchHarness:
    """Small transport harness for command-stream remote dispatch behavior."""

    def __init__(
        self,
        response_text: str | None = None,
        *,
        read_error: BaseException | None = None,
    ) -> None:
        self.response_text = response_text
        self.read_error = read_error
        self.sent: list[_RemoteDispatchRecord] = []
        self.reads: list[_RemoteReadRecord] = []

    async def send_request(
        self,
        computer_name: str,
        command: str,
        metadata: MessageMetadata,
        session_id: str | None = None,
        command_payload: JsonDict | None = None,
    ) -> str:
        del metadata
        self.sent.append(
            {
                "computer": computer_name,
                "command": command,
                "session_id": session_id,
                "command_payload": command_payload,
            }
        )
        return _MESSAGE_ID

    async def read_response(
        self,
        message_id: str,
        timeout: float = 3.0,
        target_computer: str | None = None,
    ) -> str:
        self.reads.append(
            {
                "message_id": message_id,
                "target_computer": target_computer,
                "timeout": timeout,
            }
        )
        if self.read_error is not None:
            raise self.read_error
        if self.response_text is None:
            raise AssertionError("response_text is required when read_response is reached")
        return self.response_text


class _RemoteCloseClient(_RemoteDispatchHarness):
    def __init__(self, dispatch_error: BaseException | None = None) -> None:
        super().__init__(json.dumps({"status": "success", "data": None}), read_error=dispatch_error)

    @property
    def dispatches(self) -> list[_RemoteDispatchRecord]:
        return self.sent

    async def send_request(
        self,
        computer_name: str,
        command: str,
        metadata: MessageMetadata,
        session_id: str | None = None,
        command_payload: JsonDict | None = None,
    ) -> str:
        if self.read_error is not None and not isinstance(self.read_error, TimeoutError):
            raise self.read_error
        return await super().send_request(computer_name, command, metadata, session_id, command_payload)


class _RedisReceiveHarness(_MessagingMixin):
    """Redis receive-side harness that captures response envelopes."""

    def __init__(self) -> None:
        self.client = SimpleNamespace(agent_event_handler=None)
        self.computer_name = "TestComputer"
        self.message_stream_maxlen = 100
        self._running = False
        self.responses: list[tuple[str, str]] = []

    async def send_response(self, message_id: str, data: str) -> str:
        self.responses.append((message_id, data))
        return "response-1"

    def response_envelope(self) -> JsonDict:
        assert len(self.responses) == 1
        return cast(JsonDict, json.loads(self.responses[0][1]))


async def _drive_redis_command_payload(
    monkeypatch: pytest.MonkeyPatch,
    command_payload: JsonDict,
    service: object,
) -> JsonDict:
    boundary = _RedisReceiveHarness()
    monkeypatch.setattr(command_dispatch_mod, "get_command_service", lambda: service)

    await boundary._handle_incoming_message(
        _MESSAGE_ID,
        {b"command_payload": json.dumps(command_payload).encode("utf-8")},
    )

    assert boundary.responses[0][0] == _MESSAGE_ID
    return boundary.response_envelope()


class _OwnershipDb:
    def __init__(self, session: Session | None) -> None:
        self.session = session

    async def get_session(self, session_id: str) -> Session | None:
        if self.session is None or self.session.session_id != session_id:
            return None
        return self.session


class _OwnershipCache:
    def __init__(self, sessions: list[SessionSnapshot]) -> None:
        self.sessions = sessions

    def get_sessions(self, computer: str | None = None) -> list[SessionSnapshot]:
        if computer is None:
            return self.sessions
        return [session for session in self.sessions if session.computer == computer]


def _snapshot(
    session_id: str,
    *,
    computer: str = "PeerComputer",
    human_email: str | None = None,
    human_role: str | None = None,
) -> SessionSnapshot:
    return SessionSnapshot(
        session_id=session_id,
        last_input_origin="terminal",
        title="remote session",
        thinking_mode="slow",
        active_agent="claude",
        status="active",
        computer=computer,
        human_email=human_email,
        human_role=human_role,
    )


def _install_member_identity_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    class _MemberIdentityResolver:
        registered_people_count = 1
        is_multi_user = False

        @staticmethod
        def resolve_by_email(email: str) -> IdentityContext:
            return IdentityContext(
                person_name="Member",
                person_email=email.strip().lower(),
                person_role="member",
            )

    monkeypatch.setattr(auth_mod, "get_identity_resolver", lambda: _MemberIdentityResolver())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_session(
    api: AsyncClient,
    *,
    human_role: str | None = None,
    human_email: str | None = None,
    metadata: dict | None = None,
    project_path: str | None = None,
) -> dict:
    """POST /sessions and return the response JSON."""
    payload: dict = {
        "computer": "TestComputer",
        "project_path": project_path or "/tmp",
        "agent": "claude",
        "thinking_mode": "fast",
        "title": "functional-test",
        "launch_kind": "empty",
    }
    if human_role is not None:
        payload["human_role"] = human_role
    if human_email is not None:
        payload["human_email"] = human_email
    if metadata is not None:
        payload["metadata"] = metadata
    resp = await api.post("/sessions", json=payload)
    assert resp.status_code == 200, f"session creation failed: {resp.text}"
    return resp.json()


class _AgentThenMessageBootstrapHarness(daemon_session_mod._DaemonSessionMixin):
    def __init__(self, command_service: CommandService) -> None:
        self.command_service = command_service
        self.agent_coordinator = None
        self.started_polling: list[tuple[str, str]] = []
        self.polled: list[tuple[str, str]] = []
        self.launch_results: list[dict[str, str]] = []

    async def _start_polling_for_session(self, session_id: str, tmux_session_name: str) -> None:
        self.started_polling.append((session_id, tmux_session_name))

    async def _poll_and_send_output(self, session_id: str, tmux_session_name: str) -> None:
        self.polled.append((session_id, tmux_session_name))

    async def _execute_launch_intent(
        self,
        session_id: str,
        launch_intent: SessionLaunchIntent | None,
    ) -> dict[str, str]:
        result = await super()._execute_launch_intent(session_id, launch_intent)
        self.launch_results.append(result)
        return result


async def _await_bootstrap_tasks(tasks: list[asyncio.Future[object]]) -> None:
    await asyncio.gather(*tasks)


async def _wait_until(predicate: Callable[[], bool], *, timeout_s: float = 1.0) -> None:
    deadline = datetime.now(UTC) + timedelta(seconds=timeout_s)
    while datetime.now(UTC) < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    assert predicate()


async def _install_agent_then_message_route_harness(
    api: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    pane_output: str | list[str],
    emit_turn_on_enter: bool,
    emit_ready_on_start: bool = True,
) -> tuple[_AgentThenMessageBootstrapHarness, list[asyncio.Future[object]], AsyncMock, AsyncMock, AsyncMock]:
    monkeypatch.setattr(daemon_session_mod, "db", api.db)
    monkeypatch.setattr(session_bootstrap_mod, "db", api.db)
    monkeypatch.setattr(agent_handler_mod, "db", api.db)
    monkeypatch.setattr(command_utils_mod, "db", api.db)

    command_service = get_command_service()
    harness = _AgentThenMessageBootstrapHarness(command_service)
    tasks: list[asyncio.Future[object]] = []
    session_tmpdirs: dict[str, Path] = {}

    def _queue_background_task(task: Awaitable[object], label: str) -> None:
        queued = asyncio.ensure_future(task)
        queued.set_name(label)
        tasks.append(queued)

    async def _execute_terminal_command(
        session_id: str,
        command: str,
        title: str | None,
        send_enter: bool,
    ) -> bool:
        del command, title, send_enter
        if emit_ready_on_start:
            await event_bus.emit(
                TeleClaudeEvents.AGENT_READY,
                SessionLifecycleContext(session_id=session_id),
                visibility=EventVisibility.LOCAL,
            )
        return True

    async def _ensure_tmux_session(
        name: str,
        working_dir: str,
        cols: int = 80,
        rows: int = 24,
        session_id: str | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> bool:
        del name, working_dir, cols, rows, env_vars
        if session_id:
            session_tmpdir = tmp_path / "session-tmp" / session_id
            session_tmpdir.mkdir(parents=True, exist_ok=True)
            session_tmpdirs[session_id] = session_tmpdir
        return True

    def _get_session_tmpdir(session_id: str) -> Path | None:
        return session_tmpdirs.get(session_id)

    async def _send_enter(tmux_session_name: str | None) -> bool:
        if emit_turn_on_enter and tmux_session_name:
            session_id = tmux_session_name.removeprefix("tc_")
            await event_bus.emit(
                TeleClaudeEvents.AGENT_ACTIVITY,
                UserPromptSubmitActivityEvent(
                    session_id=session_id,
                    event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
                ),
                visibility=EventVisibility.LOCAL,
            )
        return True

    paste_recorder = AsyncMock(return_value=True)
    enter_recorder = AsyncMock(side_effect=_send_enter)
    pane_outputs = [pane_output] if isinstance(pane_output, str) else list(pane_output)

    async def _capture_pane(_tmux_session_name: str | None) -> str:
        if len(pane_outputs) == 3:
            if paste_recorder.await_count == 0:
                return pane_outputs[0]
            if enter_recorder.await_count == 0:
                return pane_outputs[1]
            return pane_outputs[2]
        if len(pane_outputs) == 2:
            return pane_outputs[0] if paste_recorder.await_count == 0 else pane_outputs[1]
        if len(pane_outputs) > 1:
            return pane_outputs.pop(0)
        return pane_outputs[0]

    capture_recorder = AsyncMock(side_effect=_capture_pane)

    command_service._bootstrap_session = harness._bootstrap_session_resources  # pyright: ignore[reportPrivateUsage]
    command_service._queue_background_task = _queue_background_task  # pyright: ignore[reportPrivateUsage]
    command_service._execute_terminal_command = _execute_terminal_command  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(tmux_bridge, "ensure_tmux_session", _ensure_tmux_session)
    monkeypatch.setattr(tmux_bridge, "get_session_tmpdir", _get_session_tmpdir)
    monkeypatch.setattr(tmux_bridge, "paste_text_existing_tmux", paste_recorder)
    monkeypatch.setattr(tmux_bridge, "send_enter", enter_recorder)
    monkeypatch.setattr(tmux_bridge, "capture_pane", capture_recorder)
    monkeypatch.setattr(tmux_bridge, "is_process_running", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_io, "INJECT_TURN_START_TIMEOUT_S", 0.05)
    monkeypatch.setattr(tmux_io, "INJECT_PASTE_VISIBLE_TIMEOUT_S", 0.05)
    monkeypatch.setattr(tmux_io, "INJECT_PROMPT_OBSERVE_INTERVAL_S", 0.01)
    monkeypatch.setattr(tmux_io, "INJECT_SUBMIT_RETRY_DELAYS_S", (0.05, 0.05, 0.05))

    return harness, tasks, paste_recorder, enter_recorder, capture_recorder


async def _get_session_from_db(api: AsyncClient, session_id: str) -> Any:
    """Load session directly from DB (attached to the client by conftest)."""
    return await api.db.get_session(session_id)


async def _post_agent_then_message_session(
    api: AsyncClient,
    tmp_path: Path,
    message: str,
    *,
    agent: AgentName = AgentName.CODEX,
) -> _CreateSessionResponse:
    resp = await api.post(
        "/sessions",
        json={
            "computer": "TestComputer",
            "project_path": str(tmp_path),
            "agent": agent.value,
            "thinking_mode": "fast",
            "human_email": "test@test.com",
            "human_role": "admin",
            "message": message,
        },
    )
    assert resp.status_code == 200, f"session creation failed: {resp.text}"
    return cast(_CreateSessionResponse, resp.json())


@pytest.mark.spec(_SPEC, "UC-SL24")
async def test_agent_then_message_create_confirms_user_turn_delivery(
    api: AsyncClient,
    cluster_event_bus: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del cluster_event_bus
    message = (
        "Read /Users/Morriz/.teleclaude/commands/next-review-plan.md and follow it exactly as "
        "the active instruction set for this session.\n\n"
        "Treat the following as provided inputs to that instruction set:\n"
        "per-domain-symlink-single-owner"
    )
    prompt_marker = AgentName.CODEX.prompt_marker.strip()
    harness, tasks, paste_recorder, enter_recorder, capture_recorder = await _install_agent_then_message_route_harness(
        api,
        tmp_path,
        monkeypatch,
        pane_output="\n".join(
            [
                f"{prompt_marker} Read /Users/Morriz/.teleclaude/commands/next-review-plan.md and follow it exactly as the active instruction set",
                "  for this session.",
                "",
                "  Treat the following as provided inputs to that instruction set:",
                "  per-domain-symlink-single-owner",
                "",
                "  Create a plan?  shift + tab use Plan mode   esc dismiss",
            ]
        ),
        emit_turn_on_enter=True,
    )

    data = await _post_agent_then_message_session(api, tmp_path, message)
    await _await_bootstrap_tasks(tasks)

    session_id = data["session_id"]
    assert paste_recorder.await_count == 1
    assert enter_recorder.await_count == 1
    assert capture_recorder.await_count >= 1
    assert harness.polled == [(session_id, data["tmux_session_name"])]


@pytest.mark.spec(_SPEC, "UC-SL24")
@pytest.mark.parametrize(
    "post_paste_input",
    [
        pytest.param(
            "Read /Users/Morriz/.teleclaude/commands/next-review-plan.md and follow it exac",
            id="partial-render",
        ),
        pytest.param("[Pasted Content 1080 chars]", id="collapsed-marker"),
    ],
)
async def test_agent_then_message_create_submits_any_new_codex_live_input_after_paste(
    api: AsyncClient,
    cluster_event_bus: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    post_paste_input: str,
) -> None:
    del cluster_event_bus
    message = (
        "Read /Users/Morriz/.teleclaude/commands/next-review-plan.md and follow it exactly as "
        "the active instruction set for this session.\n\n"
        "Treat the following as provided inputs to that instruction set:\n"
        "fix-next-integrate-regression"
    )
    prompt_marker = AgentName.CODEX.prompt_marker.strip()
    harness, tasks, paste_recorder, enter_recorder, capture_recorder = await _install_agent_then_message_route_harness(
        api,
        tmp_path,
        monkeypatch,
        pane_output=[
            f"{prompt_marker} \n\n  gpt-5.5 high · ~/Workspace/InstruktAI/TeleClaude · main",
            "\n".join(
                [
                    f"{prompt_marker} {post_paste_input}",
                    "",
                    "  Create a plan?  shift + tab use Plan mode   esc dismiss",
                ]
            ),
        ],
        emit_turn_on_enter=True,
    )

    data = await _post_agent_then_message_session(api, tmp_path, message)
    await _await_bootstrap_tasks(tasks)

    session_id = data["session_id"]
    assert paste_recorder.await_count == 1
    assert enter_recorder.await_count == 1
    assert capture_recorder.await_count >= 2
    assert harness.polled == [(session_id, data["tmux_session_name"])]


@pytest.mark.spec(_SPEC, "UC-SL24")
async def test_agent_then_message_create_does_not_inject_while_codex_is_working(
    api: AsyncClient,
    cluster_event_bus: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del cluster_event_bus
    message = "must wait until codex is idle"
    prompt_marker = AgentName.CODEX.prompt_marker.strip()
    harness, tasks, paste_recorder, enter_recorder, capture_recorder = await _install_agent_then_message_route_harness(
        api,
        tmp_path,
        monkeypatch,
        pane_output="\n".join(
            [
                f"{prompt_marker} previous user input",
                "\u2022 Working (esc to interrupt)",
                "? for shortcuts",
            ]
        ),
        emit_turn_on_enter=True,
        emit_ready_on_start=False,
    )
    monkeypatch.setattr(daemon_session_mod, "AGENT_PROMPT_READY_TIMEOUT_S", 0.05)
    monkeypatch.setattr(daemon_session_mod, "AGENT_START_STABILIZE_QUIET_S", 0.0)

    data = await _post_agent_then_message_session(api, tmp_path, message)
    await _await_bootstrap_tasks(tasks)

    assert paste_recorder.await_count == 0
    assert enter_recorder.await_count == 0
    assert capture_recorder.await_count >= 1
    assert len(harness.launch_results) == 1
    assert harness.launch_results[0]["status"] == ResultStatus.ERROR.value
    assert harness.launch_results[0]["message"]
    assert harness.polled == []
    assert data["session_id"]


@pytest.mark.spec(_SPEC, "UC-SL25")
async def test_agent_then_message_create_retries_enter_without_repaste_when_turn_start_missing(
    api: AsyncClient,
    cluster_event_bus: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del cluster_event_bus
    message = "unconfirmed startup prompt"
    harness, tasks, paste_recorder, enter_recorder, _capture_recorder = await _install_agent_then_message_route_harness(
        api,
        tmp_path,
        monkeypatch,
        pane_output=f"{AgentName.CODEX.prompt_marker.strip()} {message}",
        emit_turn_on_enter=False,
    )

    await _post_agent_then_message_session(api, tmp_path, message)
    await _await_bootstrap_tasks(tasks)

    assert paste_recorder.await_count == 1
    assert enter_recorder.await_count == 3
    assert harness.polled == []
    assert harness.launch_results
    assert harness.launch_results[0]["status"] != "success"


@pytest.mark.spec(_SPEC, "UC-SL24")
async def test_agent_then_message_create_accepts_claude_prompt_state_after_enter_without_submit_hook(
    api: AsyncClient,
    cluster_event_bus: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del cluster_event_bus
    message = "startup prompt hidden behind a collapsed Claude paste chip"
    prompt_marker = AgentName.CLAUDE.prompt_marker
    harness, tasks, paste_recorder, enter_recorder, capture_recorder = await _install_agent_then_message_route_harness(
        api,
        tmp_path,
        monkeypatch,
        pane_output=[
            f"{prompt_marker} ",
            "\n".join(
                [
                    f"{prompt_marker} [Pasted text #1 +4 lines]",
                    "────────────────────────────────────────────────────────────────",
                ]
            ),
            f"{prompt_marker} ",
        ],
        emit_turn_on_enter=False,
    )

    data = await _post_agent_then_message_session(api, tmp_path, message, agent=AgentName.CLAUDE)
    await _await_bootstrap_tasks(tasks)

    session_id = data["session_id"]
    assert paste_recorder.await_count == 1
    assert enter_recorder.await_count == 1
    assert capture_recorder.await_count >= 3
    assert harness.launch_results
    assert harness.launch_results[0]["status"] == ResultStatus.SUCCESS
    assert harness.polled == [(session_id, data["tmux_session_name"])]


@pytest.mark.spec(_SPEC, "UC-SL24")
async def test_agent_then_message_create_accepts_gemini_collapsed_paste_prompt_state_without_submit_hook(
    api: AsyncClient,
    cluster_event_bus: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del cluster_event_bus
    message = "startup prompt hidden behind a collapsed Gemini paste chip"
    harness, tasks, paste_recorder, enter_recorder, _capture_recorder = await _install_agent_then_message_route_harness(
        api,
        tmp_path,
        monkeypatch,
        pane_output=[
            "> \n? for shortcuts",
            "> [Pasted text #1 +4 lines]\n? for shortcuts",
            "> \n? for shortcuts",
        ],
        emit_turn_on_enter=False,
    )

    data = await _post_agent_then_message_session(api, tmp_path, message, agent=AgentName.GEMINI)
    await _await_bootstrap_tasks(tasks)

    session_id = data["session_id"]
    assert paste_recorder.await_count == 1
    assert enter_recorder.await_count == 1
    assert harness.launch_results
    assert harness.launch_results[0]["status"] == ResultStatus.SUCCESS
    assert harness.polled == [(session_id, data["tmux_session_name"])]


@pytest.mark.spec(_SPEC, "UC-SL26")
@pytest.mark.parametrize(
    "scrollback_tail",
    [
        pytest.param(
            [
                "Previous assistant response line 1.",
                "Previous assistant response line 2.",
                "Previous assistant response line 3.",
            ],
            id="ordinary-output",
        ),
        pytest.param(
            [
                "• Thinking (1s • esc to interrupt)",
                "Previous response line.",
            ],
            id="near-bottom-submitted-boundary",
        ),
        pytest.param(
            [
                "• Thinking (1s • esc to interrupt)",
                "Completed output line 1.",
                "Completed output line 2.",
                "Completed output line 3.",
                "Completed output line 4.",
                "Completed output line 5.",
            ],
            id="submitted-boundary",
        ),
    ],
)
async def test_agent_then_message_create_ignores_scrollback_prompt_text(
    api: AsyncClient,
    cluster_event_bus: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scrollback_tail: list[str],
) -> None:
    del cluster_event_bus
    message = "historical startup prompt"
    prompt_marker = AgentName.CODEX.prompt_marker.strip()
    harness, tasks, paste_recorder, enter_recorder, _capture_recorder = await _install_agent_then_message_route_harness(
        api,
        tmp_path,
        monkeypatch,
        pane_output="\n".join(
            [
                f"{prompt_marker} {message}",
                *scrollback_tail,
            ]
        ),
        emit_turn_on_enter=False,
    )

    await _post_agent_then_message_session(api, tmp_path, message)
    await _await_bootstrap_tasks(tasks)

    assert paste_recorder.await_count == 1
    assert enter_recorder.await_count == 0
    assert harness.polled == []
    assert harness.launch_results
    assert harness.launch_results[0]["status"] != "success"


# ---------------------------------------------------------------------------
# Remote dispatch primitive
# ---------------------------------------------------------------------------


async def test_forward_command_to_peer_returns_success_envelope_data() -> None:
    envelope = json.dumps({"status": "success", "data": {"accepted": True}})
    client = _RemoteDispatchHarness(envelope)
    command = KeysCommand(session_id="session-1", key="enter", args=["1"])
    command.computer = "PeerComputer"

    data = await forward_command_to_peer(client, command)

    assert data == {"accepted": True}
    assert client.sent == [
        {
            "computer": "PeerComputer",
            "command": "keys",
            "session_id": "session-1",
            "command_payload": command.to_dict(),
        }
    ]
    assert client.reads == [
        {
            "message_id": "message-1",
            "target_computer": "PeerComputer",
            "timeout": 10.0,
        }
    ]


async def test_forward_command_to_peer_error_envelope_raises_domain_error() -> None:
    envelope = json.dumps({"status": "error", "error": "peer rejected close"})
    client = _RemoteDispatchHarness(envelope)
    command = KeysCommand(session_id="session-1", key="enter")
    command.computer = "PeerComputer"

    with pytest.raises(RemoteDispatchError):
        await forward_command_to_peer(client, command)


async def test_forward_command_to_peer_timeout_propagates() -> None:
    client = _RemoteDispatchHarness(read_error=TimeoutError())
    command = KeysCommand(session_id="session-1", key="enter")
    command.computer = "PeerComputer"

    with pytest.raises(TimeoutError):
        await forward_command_to_peer(client, command)


async def test_forward_command_to_peer_fire_and_forget_sends_command_without_reading_response() -> None:
    client = _RemoteDispatchHarness()
    command = CloseSessionCommand(session_id="session-1")
    command.computer = "PeerComputer"

    data = await forward_command_to_peer(client, command)

    assert data is None
    assert client.sent == [
        {
            "computer": "PeerComputer",
            "command": "close_session",
            "session_id": "session-1",
            "command_payload": command.to_dict(),
        }
    ]
    assert client.reads == []


async def test_redis_command_payload_round_trips_create_session_and_returns_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[CreateSessionCommand] = []

    async def create_session(command: CreateSessionCommand) -> JsonDict:
        seen.append(command)
        return {
            "session_id": _CREATED_SESSION_ID,
            "tmux_session_name": _TMUX_CREATED_SESSION,
            "agent": "claude",
        }

    command = CreateSessionCommand(
        project_path=_PROJECT_PATH,
        origin=_TERMINAL_ORIGIN,
        initial_input=_HELLO_TEXT,
        human_email="human@example.test",
        human_role="admin",
    )
    command.computer = _PEER_COMPUTER

    envelope = await _drive_redis_command_payload(
        monkeypatch,
        command.to_dict(),
        SimpleNamespace(create_session=create_session),
    )

    assert envelope == {
        "status": "success",
        "data": {
            "session_id": _CREATED_SESSION_ID,
            "tmux_session_name": _TMUX_CREATED_SESSION,
            "agent": "claude",
        },
    }
    assert len(seen) == 1
    assert isinstance(seen[0], CreateSessionCommand)
    assert seen[0].project_path == _PROJECT_PATH
    assert seen[0].origin == _TERMINAL_ORIGIN
    assert seen[0].initial_input == _HELLO_TEXT
    assert seen[0].computer == _PEER_COMPUTER


async def test_redis_command_payload_round_trips_keys_and_executes_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[KeysCommand] = []

    async def keys(command: KeysCommand) -> JsonDict:
        seen.append(command)
        return {"sent": True}

    command = KeysCommand(session_id=_SESSION_ID, key=_KEY_ENTER, args=["2"])
    command.computer = _PEER_COMPUTER

    envelope = await _drive_redis_command_payload(
        monkeypatch,
        command.to_dict(),
        SimpleNamespace(keys=keys),
    )

    assert envelope == {"status": "success", "data": {"sent": True}}
    assert len(seen) == 1
    assert isinstance(seen[0], KeysCommand)
    assert seen[0].session_id == _SESSION_ID
    assert seen[0].key == _KEY_ENTER
    assert seen[0].args == ["2"]
    assert seen[0].computer == _PEER_COMPUTER


async def test_redis_command_payload_round_trips_close_and_preserves_fire_and_forget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[CloseSessionCommand] = []

    async def close_session(command: CloseSessionCommand) -> None:
        seen.append(command)

    command = CloseSessionCommand(session_id=_SESSION_ID)
    command.computer = _PEER_COMPUTER

    envelope = await _drive_redis_command_payload(
        monkeypatch,
        command.to_dict(),
        SimpleNamespace(close_session=close_session),
    )

    assert envelope == {"status": "success", "data": None}
    assert len(seen) == 1
    assert isinstance(seen[0], CloseSessionCommand)
    assert seen[0].session_id == _SESSION_ID
    assert seen[0].response_mode.value == _FIRE_AND_FORGET_RESPONSE_MODE
    assert seen[0].computer == _PEER_COMPUTER


async def test_redis_command_payload_round_trips_unsubscribe_and_returns_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[UnsubscribeSessionCommand] = []

    async def unsubscribe(command: UnsubscribeSessionCommand) -> JsonDict:
        seen.append(command)
        return {"listener_removed": True, "link_closed": True, "link_id": "link-1"}

    command = UnsubscribeSessionCommand(session_id=_TARGET_SESSION_ID, caller_session_id=_CALLER_SESSION_ID)
    command.computer = _PEER_COMPUTER

    envelope = await _drive_redis_command_payload(
        monkeypatch,
        command.to_dict(),
        SimpleNamespace(unsubscribe=unsubscribe),
    )

    assert envelope == {
        "status": "success",
        "data": {"listener_removed": True, "link_closed": True, "link_id": "link-1"},
    }
    assert len(seen) == 1
    assert isinstance(seen[0], UnsubscribeSessionCommand)
    assert seen[0].session_id == _TARGET_SESSION_ID
    assert seen[0].caller_session_id == _CALLER_SESSION_ID
    assert seen[0].computer == _PEER_COMPUTER


# ---------------------------------------------------------------------------
# Session ownership resolver
# ---------------------------------------------------------------------------


async def test_session_ownership_resolver_prefers_local_database() -> None:
    local = Session(
        session_id="session-1",
        computer_name="TestComputer",
        tmux_session_name="tc-session-1",
        title="local session",
    )

    ownership = await resolve_session_ownership(
        "session-1",
        db=_OwnershipDb(local),
        cache=_OwnershipCache([_snapshot("session-1")]),
    )

    assert isinstance(ownership, LocalOwnership)
    assert ownership.session is local


async def test_session_ownership_resolver_returns_cached_remote_owner() -> None:
    peer = "PeerComputer"
    snapshot = _snapshot("session-1", computer=peer)

    ownership = await resolve_session_ownership(
        "session-1",
        db=_OwnershipDb(None),
        cache=_OwnershipCache([snapshot]),
    )

    assert isinstance(ownership, RemoteOwnership)
    assert ownership.computer == peer
    assert ownership.snapshot is snapshot


async def test_session_ownership_resolver_returns_none_for_unknown_session() -> None:
    ownership = await resolve_session_ownership(
        "missing-session",
        db=_OwnershipDb(None),
        cache=_OwnershipCache([_snapshot("session-1")]),
    )

    assert ownership is None


# ---------------------------------------------------------------------------
# Remote close command handler
# ---------------------------------------------------------------------------


async def test_close_session_for_peer_owned_row_dispatches_command_typed_remote_close(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del api
    client = _RemoteCloseClient()
    session = Session(
        session_id="session-1",
        computer_name="PeerComputer",
        tmux_session_name="tc-session-1",
        title="remote session",
    )
    monkeypatch.setattr(session_handler_mod.tmux_bridge, "session_exists", AsyncMock(return_value=False))

    await session_handler_mod.close_session.__wrapped__(
        session,
        CloseSessionCommand(session_id="session-1"),
        client,
    )

    assert client.dispatches == [
        {
            "computer": "PeerComputer",
            "command": "close_session",
            "session_id": "session-1",
            "command_payload": {
                "command_type": "close_session",
                "computer": "PeerComputer",
                "request_id": None,
                "response_mode": "fire_and_forget",
                "completion_event": "session.close_completed",
                "session_id": "session-1",
            },
        }
    ]


async def test_close_session_for_locally_present_row_does_not_dispatch_remote_close(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del api
    client = _RemoteCloseClient()
    session = Session(
        session_id="session-1",
        computer_name="PeerComputer",
        tmux_session_name="tc-session-1",
        title="local session",
    )
    terminate = AsyncMock(return_value=True)
    monkeypatch.setattr(session_handler_mod.tmux_bridge, "session_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(session_handler_mod, "terminate_session", terminate)
    monkeypatch.setattr(session_handler_mod.event_bus, "emit", lambda *args, **kwargs: None)

    await session_handler_mod.close_session.__wrapped__(
        session,
        CloseSessionCommand(session_id="session-1"),
        client,
    )

    assert client.dispatches == []
    terminate.assert_awaited_once()


# ---------------------------------------------------------------------------
# Remote send-keys API boundary
# ---------------------------------------------------------------------------


async def test_send_keys_for_peer_targeted_session_dispatches_remote_and_does_not_run_locally(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adopting a peer-owned headless session forwards the key to the owning peer.

    Regression for the reported 500 ("Session ... not found - this should not happen"):
    the endpoint must dispatch to the owning peer instead of resolving the key against
    the local DB, which never holds a peer-owned session row.
    """
    client = _RemoteCloseClient()
    local_keys = AsyncMock()
    monkeypatch.setattr(sessions_actions_routes._STATE, "client", client)
    monkeypatch.setattr(command_dispatch_mod, "get_command_service", lambda: SimpleNamespace(keys=local_keys))

    response = await api.post(
        "/sessions/remote-session/keys",
        params={"computer": "PeerComputer"},
        json={"key": "enter", "count": 1},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    local_keys.assert_not_awaited()
    assert client.dispatches == [
        {
            "computer": "PeerComputer",
            "command": "keys",
            "session_id": "remote-session",
            "command_payload": {
                "command_type": "keys",
                "computer": "PeerComputer",
                "request_id": None,
                "response_mode": "immediate",
                "completion_event": None,
                "session_id": "remote-session",
                "key": "enter",
                "args": ["1"],
            },
        }
    ]


async def test_send_keys_for_local_target_runs_locally_and_does_not_dispatch_remote(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A send-keys request with no remote target executes against the local session store."""
    client = _RemoteCloseClient()
    local_keys = AsyncMock()
    monkeypatch.setattr(sessions_actions_routes._STATE, "client", client)
    monkeypatch.setattr(command_dispatch_mod, "get_command_service", lambda: SimpleNamespace(keys=local_keys))

    response = await api.post(
        "/sessions/local-session/keys",
        json={"key": "enter", "count": 1},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    local_keys.assert_awaited_once()
    assert client.dispatches == []


async def test_send_keys_for_peer_rejects_non_key_command_without_dispatch(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A peer-targeted request whose key is not a key command is rejected before peer dispatch.

    Regression guard: the keys route is cleared for send-keys, not session close, so it must
    not forward ``end_session`` (which the peer mapper resolves to CloseSessionCommand).
    """
    client = _RemoteCloseClient()
    local_keys = AsyncMock()
    monkeypatch.setattr(sessions_actions_routes._STATE, "client", client)
    monkeypatch.setattr(command_dispatch_mod, "get_command_service", lambda: SimpleNamespace(keys=local_keys))

    response = await api.post(
        "/sessions/remote-session/keys",
        params={"computer": "PeerComputer"},
        json={"key": "end_session"},
    )

    assert response.status_code == 400
    local_keys.assert_not_awaited()
    assert client.dispatches == []


# ---------------------------------------------------------------------------
# Unsubscribe command route
# ---------------------------------------------------------------------------


async def test_unsubscribe_local_removes_listener_and_direct_link(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_listeners_mod, "db", api.db)
    caller = await _create_session(api)
    target = await _create_session(api)
    caller_id = caller["session_id"]
    target_id = target["session_id"]
    await session_listeners_mod.register_listener(
        target_session_id=target_id,
        caller_session_id=caller_id,
        caller_tmux_session="tc-caller",
    )
    link = await session_listeners_mod.create_link(mode="direct_link", created_by_session_id=caller_id)
    await session_listeners_mod.add_link_member(link_id=link.link_id, session_id=caller_id)
    await session_listeners_mod.add_link_member(link_id=link.link_id, session_id=target_id)
    token = await api.db.issue_session_token(caller_id, f"system:{caller_id}", "admin")

    response = await api.post(f"/sessions/{target_id}/unsubscribe", headers={"x-session-token": token})

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "listener_removed": True,
        "link_closed": True,
        "link_id": link.link_id,
    }


async def test_unsubscribe_local_empty_state_is_idempotent(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_listeners_mod, "db", api.db)
    caller = await _create_session(api)
    target = await _create_session(api)
    caller_id = caller["session_id"]
    target_id = target["session_id"]
    token = await api.db.issue_session_token(caller_id, f"system:{caller_id}", "admin")

    response = await api.post(f"/sessions/{target_id}/unsubscribe", headers={"x-session-token": token})

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "listener_removed": False,
        "link_closed": False,
        "link_id": None,
    }


async def test_unsubscribe_remote_forwards_command_and_relays_payload(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = await _create_session(api)
    caller_id = caller["session_id"]
    token = await api.db.issue_session_token(caller_id, f"system:{caller_id}", "admin")
    client = _RemoteDispatchHarness(
        json.dumps(
            {
                "status": "success",
                "data": {"listener_removed": True, "link_closed": False, "link_id": None},
            }
        )
    )
    monkeypatch.setattr(sessions_actions_routes._STATE, "client", client)

    response = await api.post(
        "/sessions/remote-session/unsubscribe",
        params={"computer": "PeerComputer"},
        headers={"x-session-token": token},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "listener_removed": True,
        "link_closed": False,
        "link_id": None,
    }
    assert client.sent == [
        {
            "computer": "PeerComputer",
            "command": "unsubscribe_session",
            "session_id": "remote-session",
            "command_payload": {
                "command_type": "unsubscribe_session",
                "computer": "PeerComputer",
                "request_id": None,
                "response_mode": "immediate",
                "completion_event": None,
                "session_id": "remote-session",
                "caller_session_id": caller_id,
            },
        }
    ]


# ---------------------------------------------------------------------------
# Remote close API boundary
# ---------------------------------------------------------------------------


async def test_delete_remote_session_forwards_to_cached_owner_and_returns_completion_event(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RemoteCloseClient()
    cache = _OwnershipCache(
        [
            _snapshot(
                "remote-session",
                computer="PeerComputer",
                human_email="owner@example.com",
                human_role="member",
            )
        ]
    )
    _install_member_identity_resolver(monkeypatch)
    monkeypatch.setattr(sessions_routes._STATE, "client", client)
    monkeypatch.setattr(sessions_routes._STATE, "cache", cache)

    response = await api.delete(
        "/sessions/remote-session",
        params={"computer": "PeerComputer"},
        headers={
            "x-web-user-email": "owner@example.com",
            "x-web-user-role": "member",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["completion_event"] == CloseSessionCommand(session_id="remote-session").completion_event
    assert body["message"]
    assert client.dispatches == [
        {
            "computer": "PeerComputer",
            "command": "close_session",
            "session_id": "remote-session",
            "command_payload": {
                "command_type": "close_session",
                "computer": "PeerComputer",
                "request_id": None,
                "response_mode": "fire_and_forget",
                "completion_event": "session.close_completed",
                "session_id": "remote-session",
            },
        }
    ]


async def test_remote_message_forwards_process_message_with_computer(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = await _create_session(api)
    session_id = session["session_id"]
    client = _RemoteDispatchHarness(json.dumps({"status": "success", "data": None}))
    monkeypatch.setattr(sessions_routes._STATE, "client", client)

    response = await api.post(
        f"/sessions/{session_id}/message",
        params={"computer": "PeerComputer"},
        json={"message": "hello peer"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == _SUCCESS_STATUS
    assert client.sent == [
        {
            "computer": "PeerComputer",
            "command": "process_message",
            "session_id": session_id,
            "command_payload": {
                "command_type": "process_message",
                "computer": "PeerComputer",
                "request_id": None,
                "response_mode": "immediate",
                "completion_event": None,
                "session_id": session_id,
                "text": "hello peer",
                "origin": "terminal",
                "actor_id": None,
                "actor_name": None,
                "actor_avatar_url": None,
                "source_message_id": None,
                "source_channel_id": None,
                "origin_metadata": None,
            },
        }
    ]


async def test_remote_voice_forwards_handle_voice_with_computer(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = await _create_session(api)
    session_id = session["session_id"]
    client = _RemoteDispatchHarness(json.dumps({"status": "success", "data": None}))
    monkeypatch.setattr(sessions_actions_routes._STATE, "client", client)

    response = await api.post(
        f"/sessions/{session_id}/voice",
        params={"computer": "PeerComputer"},
        json={"file_path": "/tmp/voice.ogg", "duration": 1.5, "message_id": "m-1", "message_thread_id": 42},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    assert client.sent == [
        {
            "computer": "PeerComputer",
            "command": "handle_voice",
            "session_id": session_id,
            "command_payload": {
                "command_type": "handle_voice",
                "computer": "PeerComputer",
                "request_id": None,
                "response_mode": "immediate",
                "completion_event": None,
                "session_id": session_id,
                "file_path": "/tmp/voice.ogg",
                "duration": 1.5,
                "message_id": "m-1",
                "message_thread_id": 42,
                "origin": "terminal",
                "actor_id": None,
                "actor_name": None,
                "actor_avatar_url": None,
                "origin_metadata": None,
                "voice_transcription_id": None,
                "notice_message_id": None,
            },
        }
    ]


async def test_remote_restart_forwards_restart_command_with_computer(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = await _create_session(api)
    session_id = session["session_id"]
    client = _RemoteCloseClient()
    monkeypatch.setattr(sessions_actions_routes._STATE, "client", client)

    response = await api.post(
        f"/sessions/{session_id}/agent-restart",
        params={"computer": "PeerComputer"},
        json={"self_restart": True},
    )

    assert response.status_code == 202
    assert response.json()["status"] == _ACCEPTED_STATUS
    await _wait_until(lambda: bool(client.dispatches))
    assert client.dispatches == [
        {
            "computer": "PeerComputer",
            "command": "restart_agent",
            "session_id": session_id,
            "command_payload": {
                "command_type": "restart_agent",
                "computer": "PeerComputer",
                "request_id": None,
                "response_mode": "fire_and_forget",
                "completion_event": "agent.restart_dispatched",
                "session_id": session_id,
                "agent_name": None,
                "self_restart": True,
            },
        }
    ]


async def test_revive_local_surfaces_restart_failure(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name="tc-revive-failure",
        last_input_origin="terminal",
        title="revive failure",
        active_agent="claude",
        native_session_id="native-session",
        emit_session_started=False,
    )
    session_id = session.session_id

    async def restart_agent(command: RestartAgentCommand) -> tuple[bool, str]:
        assert command.session_id == session_id
        assert command.response_mode.value == _IMMEDIATE_RESPONSE_MODE
        return False, _RESTART_FAILURE

    monkeypatch.setattr(
        command_dispatch_mod, "get_command_service", lambda: SimpleNamespace(restart_agent=restart_agent)
    )

    response = await api.post(f"/sessions/{session_id}/revive")

    assert response.status_code == 409
    assert response.json()["detail"] == _RESTART_FAILURE


async def test_revive_remote_forwards_synchronous_restart_and_surfaces_peer_failure(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = await _create_session(api)
    session_id = session["session_id"]
    client = _RemoteDispatchHarness(json.dumps({"status": _SUCCESS_STATUS, "data": [False, _PEER_RESTART_FAILURE]}))
    monkeypatch.setattr(sessions_actions_routes._STATE, "client", client)

    response = await api.post(
        f"/sessions/{session_id}/revive",
        params={"computer": "PeerComputer"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == _PEER_RESTART_FAILURE
    assert client.sent == [
        {
            "computer": "PeerComputer",
            "command": "restart_agent",
            "session_id": session_id,
            "command_payload": {
                "command_type": "restart_agent",
                "computer": "PeerComputer",
                "request_id": None,
                "response_mode": "immediate",
                "completion_event": None,
                "session_id": session_id,
                "agent_name": None,
                "self_restart": False,
            },
        }
    ]


async def test_remote_tail_relays_session_messages_dto(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = await _create_session(api)
    session_id = session["session_id"]
    dto_payload = {
        "session_id": session_id,
        "agent": "claude",
        "last_activity": None,
        "last_input_at": None,
        "last_agent_stop_at": None,
        "agent_status": "idle",
        "messages": [
            {
                "role": "assistant",
                "type": "text",
                "text": "remote transcript",
                "timestamp": None,
                "entry_index": 0,
                "file_index": 0,
            }
        ],
    }
    client = _RemoteDispatchHarness(json.dumps({"status": "success", "data": dto_payload}))
    monkeypatch.setattr(sessions_actions_routes._STATE, "client", client)

    response = await api.get(
        f"/sessions/{session_id}/messages",
        params={"computer": "PeerComputer", "include_tools": "true", "include_thinking": "true", "tail_scope": "all"},
    )

    assert response.status_code == 200
    assert response.json() == dto_payload
    assert client.sent == [
        {
            "computer": "PeerComputer",
            "command": "get_session_messages",
            "session_id": session_id,
            "command_payload": None,
        }
    ]


async def test_redis_get_session_messages_rpc_decodes_options_and_returns_dto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: _SessionMessagesRpcCapture | None = None
    dto_payload = {
        "session_id": "remote-session",
        "agent": "claude",
        "last_activity": None,
        "last_input_at": None,
        "last_agent_stop_at": None,
        "agent_status": "idle",
        "messages": [
            {
                "role": "assistant",
                "type": "text",
                "text": "remote transcript",
                "timestamp": None,
                "entry_index": 0,
                "file_index": 0,
            }
        ],
    }

    async def build_session_messages_dto(
        session_id: str,
        *,
        recipient_email: str | None,
        recipient_role: str | None,
        options: object,
    ) -> object:
        nonlocal captured
        captured = {
            "session_id": session_id,
            "recipient_email": recipient_email,
            "recipient_role": recipient_role,
            "since": cast(str | None, options.since),
            "include_tools": cast(bool | None, options.include_tools),
            "include_thinking": bool(options.include_thinking),
            "tail_chars": int(options.tail_chars),
            "tail_scope": str(options.tail_scope),
        }
        return SimpleNamespace(model_dump=lambda mode: dto_payload)

    boundary = _RedisReceiveHarness()
    monkeypatch.setattr(redis_messaging_mod, "build_session_messages_dto", build_session_messages_dto)

    await boundary._handle_incoming_message(
        "message-1",
        {
            b"command": b"get_session_messages",
            b"session_id": b"remote-session",
            b"human_email": b"human@example.test",
            b"human_role": b"member",
            b"origin_metadata": json.dumps(
                {
                    "since": "2026-01-01T00:00:00Z",
                    "include_tools": True,
                    "include_thinking": True,
                    "tail_chars": 2048,
                    "tail_scope": "latest_turn",
                }
            ).encode("utf-8"),
        },
    )

    assert captured == {
        "session_id": "remote-session",
        "recipient_email": "human@example.test",
        "recipient_role": "member",
        "since": "2026-01-01T00:00:00Z",
        "include_tools": True,
        "include_thinking": True,
        "tail_chars": 2048,
        "tail_scope": "latest_turn",
    }
    assert boundary.response_envelope() == {"status": "success", "data": dto_payload}


async def test_tool_sessions_subcommands_thread_computer_to_api_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, str] | None, object | None]] = []

    def tool_api_call(
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: object | None = None,
    ) -> dict[str, str]:
        calls.append((method, path, params, json_body))
        return {"status": "ok"}

    monkeypatch.setattr(sessions_tool, "tool_api_call", tool_api_call)
    monkeypatch.setattr(sessions_tool, "print_json", lambda data: None)
    monkeypatch.setattr(sessions_tool, "_emit_tmux_feedback", lambda message: None)

    sessions_tool.handle_sessions_send(["session-1", "hello", "--computer", "PeerComputer"])
    sessions_tool.handle_sessions_tail(["session-1", "--computer", "PeerComputer"])
    sessions_tool.handle_sessions_unsubscribe(["session-1", "--computer", "PeerComputer"])
    sessions_tool.handle_sessions_restart(["session-1", "--computer", "PeerComputer"])
    sessions_tool.handle_sessions_run(
        [
            "--command",
            "/next-build",
            "--args",
            "slug",
            "--path",
            "/tmp/project",
            "--computer",
            "PeerComputer",
        ]
    )

    assert calls == [
        (
            "POST",
            "/sessions/session-1/message",
            {"computer": "PeerComputer"},
            {"message": "hello"},
        ),
        (
            "GET",
            "/sessions/session-1/messages",
            {"computer": "PeerComputer", "tail_scope": "latest_turn"},
            None,
        ),
        (
            "POST",
            "/sessions/session-1/unsubscribe",
            {"computer": "PeerComputer"},
            None,
        ),
        (
            "POST",
            "/sessions/session-1/agent-restart",
            {"computer": "PeerComputer"},
            None,
        ),
        (
            "POST",
            "/sessions/run",
            None,
            {
                "computer": "PeerComputer",
                "thinking_mode": "slow",
                "args": "slug",
                "command": "/next-build",
                "project": "/tmp/project",
            },
        ),
    ]


async def test_api_client_threads_computer_to_run_restart_and_revive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, str] | None, object | None]] = []
    client = TelecAPIClient()

    async def request(
        method: str,
        path: str,
        *,
        timeout: float | None = None,
        request_options: object | None = None,
    ) -> Response:
        del timeout
        params = getattr(request_options, "params", None)
        json_body = getattr(request_options, "json_body", None)
        calls.append((method, path, params, json_body))
        if path == f"/sessions/{_SESSION_ID}/agent-restart":
            return Response(202, json={"status": _ACCEPTED_STATUS})
        return Response(
            200,
            json={
                "status": "success",
                "session_id": "session-1",
                "tmux_session_name": "tc-session-1",
                "computer": "PeerComputer",
                "agent": "claude",
            },
        )

    monkeypatch.setattr(client, "_request", request)

    await client.run_session(
        command="/next-build",
        args="slug",
        project_path="/tmp/project",
        computer="PeerComputer",
    )
    assert await client.agent_restart("session-1", computer="PeerComputer") is True
    await client.revive_session("session-1", computer="PeerComputer")

    assert calls[0] == (
        "POST",
        "/sessions/run",
        None,
        {
            "computer": "PeerComputer",
            "command": "/next-build",
            "args": "slug",
            "project": "/tmp/project",
            "agent": "claude",
            "subfolder": "",
            "thinking_mode": "slow",
            "detach": False,
            "additional_context": "",
        },
    )
    assert calls[1] == (
        "POST",
        "/sessions/session-1/agent-restart",
        {"computer": "PeerComputer"},
        None,
    )
    assert calls[2] == (
        "POST",
        "/sessions/session-1/revive",
        {"computer": "PeerComputer"},
        None,
    )


async def test_delete_remote_session_rejects_non_owner_web_identity(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _OwnershipCache(
        [
            _snapshot(
                "remote-session",
                computer="PeerComputer",
                human_email="owner@example.com",
                human_role="member",
            )
        ]
    )
    _install_member_identity_resolver(monkeypatch)
    monkeypatch.setattr(sessions_routes._STATE, "client", _RemoteCloseClient())
    monkeypatch.setattr(sessions_routes._STATE, "cache", cache)

    response = await api.delete(
        "/sessions/remote-session",
        params={"computer": "PeerComputer"},
        headers={
            "x-web-user-email": "other@example.com",
            "x-web-user-role": "member",
        },
    )

    assert response.status_code == 403


async def test_delete_local_session_continues_when_manual_hold_interlock_fails(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = await _create_session(api)
    session_id = session["session_id"]
    hold = AsyncMock(side_effect=RuntimeError("hold failed"))
    close = AsyncMock()
    service = SimpleNamespace(close_session=close)
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", hold)
    monkeypatch.setattr(command_dispatch_mod, "get_command_service", lambda: service)

    # No x-session-token / x-caller-session-id → human principal (empty
    # identity.session_id), so this manual close holds the driven todo (ADR-0036).
    response = await api.delete(f"/sessions/{session_id}")

    assert response.status_code == 202
    body = response.json()
    assert body["completion_event"] == CloseSessionCommand(session_id=session_id).completion_event
    hold.assert_awaited_once_with(api.db, session_id)
    close.assert_awaited_once_with(CloseSessionCommand(session_id=session_id))


async def test_delete_human_close_sets_hold(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0036: a human-initiated close (empty identity.session_id) holds the todo."""
    session = await _create_session(api)
    session_id = session["session_id"]
    hold = AsyncMock()
    close = AsyncMock()
    service = SimpleNamespace(close_session=close)
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", hold)
    monkeypatch.setattr(command_dispatch_mod, "get_command_service", lambda: service)

    # No session token → human principal.
    response = await api.delete(f"/sessions/{session_id}")

    assert response.status_code == 202
    hold.assert_awaited_once_with(api.db, session_id)
    close.assert_awaited_once_with(CloseSessionCommand(session_id=session_id))


async def test_delete_self_close_by_agent_does_not_hold(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0036: an agent self-end (token-auth, non-empty identity.session_id) does not hold."""
    session = await _create_session(api)
    session_id = session["session_id"]
    token = await api.db.issue_session_token(session_id, f"system:{session_id}", "admin")
    hold = AsyncMock()
    close = AsyncMock()
    service = SimpleNamespace(close_session=close)
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", hold)
    monkeypatch.setattr(command_dispatch_mod, "get_command_service", lambda: service)

    # Agent identity via session token → non-empty identity.session_id.
    response = await api.delete(
        f"/sessions/{session_id}",
        headers={"x-session-token": token},
    )

    assert response.status_code == 202
    hold.assert_not_awaited()
    close.assert_awaited_once_with(CloseSessionCommand(session_id=session_id))


_SELF_END_SPEC = "project/spec/feature/identity/self-end-authorization-bypass"


@pytest.mark.spec(_SELF_END_SPEC, "UC-SE1")
async def test_self_end_parentless_driver_accepted(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    cluster_event_bus: None,
) -> None:
    """A parentless worker driver may end its own session past the verb band."""
    session = await _create_session(api)
    session_id = session["session_id"]
    # working_slug derives system_role=worker; initiator_session_id stays None (driver).
    await api.db.update_session(session_id, working_slug="some-slug")
    token = await api.db.issue_session_token(session_id, f"system:{session_id}", ROLE_WORKER)
    close = AsyncMock()
    service = SimpleNamespace(close_session=close)
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", AsyncMock())
    monkeypatch.setattr(command_dispatch_mod, "get_command_service", lambda: service)

    response = await api.delete(f"/sessions/{session_id}", headers={"x-session-token": token})

    assert response.status_code == 202
    close.assert_awaited_once_with(CloseSessionCommand(session_id=session_id))


@pytest.mark.spec(_SELF_END_SPEC, "UC-SE2")
async def test_self_end_sub_worker_rejected(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    cluster_event_bus: None,
) -> None:
    """A worker self-end with an orchestrating parent falls through to a 403."""
    session = await _create_session(api)
    session_id = session["session_id"]
    # initiator_session_id set → the session has an orchestrating parent (sub-worker).
    await api.db.update_session(session_id, working_slug="some-slug", initiator_session_id="parent-session")
    token = await api.db.issue_session_token(session_id, f"system:{session_id}", ROLE_WORKER)
    close = AsyncMock()
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", AsyncMock())
    monkeypatch.setattr(command_dispatch_mod, "get_command_service", lambda: SimpleNamespace(close_session=close))

    response = await api.delete(f"/sessions/{session_id}", headers={"x-session-token": token})

    assert response.status_code == 403
    close.assert_not_awaited()


@pytest.mark.spec(_SELF_END_SPEC, "UC-SE3")
async def test_self_end_worker_ending_other_rejected(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    cluster_event_bus: None,
) -> None:
    """A worker ending a DIFFERENT session is rejected by the standard rule."""
    caller = await _create_session(api)
    caller_id = caller["session_id"]
    target = await _create_session(api)
    target_id = target["session_id"]
    await api.db.update_session(caller_id, working_slug="some-slug")
    token = await api.db.issue_session_token(caller_id, f"system:{caller_id}", ROLE_WORKER)
    close = AsyncMock()
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", AsyncMock())
    monkeypatch.setattr(command_dispatch_mod, "get_command_service", lambda: SimpleNamespace(close_session=close))

    response = await api.delete(f"/sessions/{target_id}", headers={"x-session-token": token})

    assert response.status_code == 403
    close.assert_not_awaited()


@pytest.mark.spec(_SELF_END_SPEC, "UC-SE4")
async def test_self_end_integrator_ending_other_accepted(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    cluster_event_bus: None,
) -> None:
    """An in-band system role ending a DIFFERENT session passes the standard rule."""
    caller = await _create_session(api)
    caller_id = caller["session_id"]
    target = await _create_session(api)
    target_id = target["session_id"]
    await api.db.update_session(caller_id, system_role="integrator")
    token = await api.db.issue_session_token(caller_id, f"system:{caller_id}", "integrator")
    close = AsyncMock()
    service = SimpleNamespace(close_session=close)
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", AsyncMock())
    monkeypatch.setattr(command_dispatch_mod, "get_command_service", lambda: service)

    response = await api.delete(f"/sessions/{target_id}", headers={"x-session-token": token})

    assert response.status_code == 202
    close.assert_awaited_once_with(CloseSessionCommand(session_id=target_id))


@pytest.mark.spec(_SELF_END_SPEC, "UC-SE5")
async def test_self_end_terminal_caller_uses_human_band(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal caller (empty session_id) is evaluated against the human band."""
    session = await _create_session(api)
    session_id = session["session_id"]
    close = AsyncMock()
    service = SimpleNamespace(close_session=close)
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", AsyncMock())
    monkeypatch.setattr(command_dispatch_mod, "get_command_service", lambda: service)

    # No session token → single-user terminal admin via the human band.
    response = await api.delete(f"/sessions/{session_id}")

    assert response.status_code == 202
    close.assert_awaited_once_with(CloseSessionCommand(session_id=session_id))


@pytest.mark.spec(_SELF_END_SPEC, "UC-SE5")
async def test_self_end_terminal_caller_outside_band_rejected(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal caller whose role is outside the end human band is rejected."""
    session = await _create_session(api)
    session_id = session["session_id"]

    class _ContributorIdentityResolver:
        registered_people_count = 1
        is_multi_user = False

        @staticmethod
        def resolve_by_email(email: str) -> IdentityContext:
            return IdentityContext(
                person_name="Contributor",
                person_email=email.strip().lower(),
                person_role="contributor",
            )

    monkeypatch.setattr(auth_mod, "get_identity_resolver", lambda: _ContributorIdentityResolver())
    close = AsyncMock()
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", AsyncMock())
    monkeypatch.setattr(command_dispatch_mod, "get_command_service", lambda: SimpleNamespace(close_session=close))

    # Terminal caller (no token → empty session_id) resolving to contributor,
    # which is outside the `telec sessions end` human band {admin, member}.
    response = await api.delete(f"/sessions/{session_id}", headers={"x-web-user-email": "contrib@example.com"})

    assert response.status_code == 403
    close.assert_not_awaited()


async def test_delete_remote_session_rejects_requested_computer_mismatch(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _OwnershipCache(
        [
            _snapshot(
                "remote-session",
                computer="PeerComputer",
                human_email="owner@example.com",
                human_role="member",
            )
        ]
    )
    _install_member_identity_resolver(monkeypatch)
    monkeypatch.setattr(sessions_routes._STATE, "client", _RemoteCloseClient())
    monkeypatch.setattr(sessions_routes._STATE, "cache", cache)

    response = await api.delete(
        "/sessions/remote-session",
        params={"computer": "OtherComputer"},
        headers={
            "x-web-user-email": "owner@example.com",
            "x-web-user-role": "member",
        },
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 1. Single-user terminal caller → admin role on session record
# ---------------------------------------------------------------------------


@pytest.mark.spec(_SPEC, "UC-SL20")
async def test_single_user_session_gets_admin_from_auth(api: AsyncClient, snapshot) -> None:
    """In single-user mode, a terminal caller gets admin from the auth layer.

    The session record must have human_role='admin' — not because of a model
    default, but because verify_caller resolved the single-user identity.
    """
    data = await _create_session(api)
    session = await _get_session_from_db(api, data["session_id"])
    assert session is not None
    assert {"human_role": session.human_role} == snapshot


# ---------------------------------------------------------------------------
# 2. Explicit human_role in request is preserved
# ---------------------------------------------------------------------------


async def test_explicit_member_role_preserved(api: AsyncClient, snapshot) -> None:
    """When the request carries human_role='member', the session record
    must reflect that — not silently upgrade to admin.
    """
    data = await _create_session(api, human_role="member")
    session = await _get_session_from_db(api, data["session_id"])
    assert {"human_role": session.human_role} == snapshot


# ---------------------------------------------------------------------------
# 3. System session (with metadata.system_role) gets no human_role fallback
# ---------------------------------------------------------------------------


async def test_system_session_has_no_human_role_fallback(api: AsyncClient, snapshot) -> None:
    """A system session created with system_role metadata should not get
    human_role='admin' from a fallback. human_role comes from the auth
    layer (single-user → admin in this test), not from a model default.
    """
    data = await _create_session(
        api,
        metadata={"system_role": "system"},
    )
    session = await _get_session_from_db(api, data["session_id"])
    # human_role is set by auth (single-user → admin), not by a fallback.
    assert {"system_role": session.system_role, "human_role": session.human_role} == snapshot


# ---------------------------------------------------------------------------
# 4. Child session inherits parent's human_role
# ---------------------------------------------------------------------------


@pytest.mark.spec(_SPEC, "UC-SL2")
async def test_child_inherits_parent_human_role(api: AsyncClient, snapshot) -> None:
    """When an agent session spawns a child via POST /sessions with
    x-caller-session-id, the child should inherit the parent's human_role.
    """
    parent_data = await _create_session(api, human_role="member")
    parent_id = parent_data["session_id"]
    parent_tmux = parent_data["tmux_session_name"]

    # Child creation: agent calls from within parent session context.
    child_resp = await api.post(
        "/sessions",
        json={
            "computer": "TestComputer",
            "project_path": "/tmp",
            "agent": "claude",
            "thinking_mode": "fast",
            "title": "child-session",
            "launch_kind": "empty",
        },
        headers={
            "x-caller-session-id": parent_id,
            "x-tmux-session": parent_tmux,
        },
    )
    assert child_resp.status_code == 200, f"child creation failed: {child_resp.text}"
    child = await _get_session_from_db(api, child_resp.json()["session_id"])
    assert {"human_role": child.human_role} == snapshot
    assert child.initiator_session_id == parent_id


# ---------------------------------------------------------------------------
# 4b. Daemon-hosted operation caller authenticates without a foreign tmux factor
# ---------------------------------------------------------------------------


async def test_operation_caller_authorizes_without_ambient_tmux(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A daemon-hosted lifecycle operation builds caller identity headers from the
    contextvar override while holding no tmux pane. Honoring the caller-verification
    contract's pane-less caveat (``docs/project/spec/feature/identity/caller-verification.md``
    Known caveats: identity-context-spawned tasks without a tmux pane authenticate by
    sending no tmux signal), the client must omit ``x-tmux-session`` rather than attach
    the daemon's foreign ambient tmux session — which would 403 the caller as a session
    identity mismatch. Drives the real header-building path into the real auth boundary
    and asserts the authorization outcome (not the header dict).
    """
    caller = await _create_session(api, human_role="member")
    caller_id = caller["session_id"]

    # The daemon process has no tmux pane, so the ambient read resolves to a foreign
    # session; the operation runner installs only the caller session id via the override.
    monkeypatch.setattr(TelecAPIClient, "_read_tmux_session_name", lambda self: "tc_foreign-daemon")
    monkeypatch.setattr(api_client_mod, "get_session_token", lambda: None)
    monkeypatch.setattr(api_client_mod, "read_current_session_email", lambda: None)

    token = set_caller_session_id(caller_id)
    try:
        headers = TelecAPIClient()._build_identity_headers()
    finally:
        reset_caller_session_id(token)

    resp = await api.post(
        "/sessions",
        json={
            "computer": "TestComputer",
            "project_path": "/tmp",
            "agent": "claude",
            "thinking_mode": "fast",
            "title": "operation-dispatch",
            "launch_kind": "empty",
        },
        headers=headers,
    )

    assert resp.status_code == 200, f"operation caller rejected: {resp.status_code} {resp.text}"
    child = await _get_session_from_db(api, resp.json()["session_id"])
    assert child.initiator_session_id == caller_id


# ---------------------------------------------------------------------------
# 5. Token-authenticated session can call API endpoints
# ---------------------------------------------------------------------------


async def test_token_auth_allows_session_list(api: AsyncClient) -> None:
    """An agent session with a valid token can call GET /sessions.

    The token must authenticate successfully and the endpoint must return 200.
    Sessions in 'initializing' status are excluded from list by default, so we
    verify auth works (200) rather than checking session membership.
    """
    data = await _create_session(api)
    session_id = data["session_id"]

    # Issue a token (simulating what the daemon does at session bootstrap).
    token = await api.db.issue_session_token(session_id, f"system:{session_id}", "admin")

    resp = await api.get(
        "/sessions",
        params={"all": "true"},
        headers={"x-session-token": token},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# 6. Token for a session with human_role=None still works
# ---------------------------------------------------------------------------


async def test_token_auth_with_null_human_role(api: AsyncClient, cluster_event_bus: None) -> None:
    """A system-spawned session may have human_role=None in the DB.
    Token auth should still work — principal_role from the token record
    is used for clearance when human_role is absent.
    """
    # Create session, then manually clear human_role to simulate a system session.
    data = await _create_session(api)
    session_id = data["session_id"]
    await api.db.update_session(session_id, human_role=None)

    token = await api.db.issue_session_token(session_id, f"system:{session_id}", "admin")

    resp = await api.get(
        "/sessions",
        headers={"x-session-token": token},
    )
    assert resp.status_code == 200


@pytest.mark.spec(_SPEC, "UC-SL22")
async def test_closed_session_snapshots_report_idle_agent_status(snapshot) -> None:
    now = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)

    def session_snapshot(
        session_id: str,
        *,
        lifecycle_status: str,
        closed_at: datetime | None,
        last_input_at: datetime | None,
        last_agent_stop_at: datetime | None,
    ) -> dict[str, str | None]:
        session = Session(
            session_id=session_id,
            computer_name="TestComputer",
            tmux_session_name=session_id,
            title=session_id,
            active_agent="claude",
            lifecycle_status=lifecycle_status,
            closed_at=closed_at,
            last_activity=now,
            last_message_sent_at=last_input_at,
            last_agent_stop_at=last_agent_stop_at,
        )
        projected = SessionSnapshot.from_db_session(session)
        return {
            "status": projected.status,
            "closed_at": projected.closed_at,
            "last_agent_stop_at": projected.last_agent_stop_at,
            "agent_status": projected.agent_status,
        }

    projections = {
        "closed_status_without_stop": session_snapshot(
            "closed-status",
            lifecycle_status="closed",
            closed_at=None,
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=None,
        ),
        "closing_status_without_stop": session_snapshot(
            "closing-status",
            lifecycle_status="closing",
            closed_at=None,
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=None,
        ),
        "closed_at_marker_without_stop": session_snapshot(
            "closed-at-marker",
            lifecycle_status="active",
            closed_at=now - timedelta(minutes=1),
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=None,
        ),
        "active_without_stop": session_snapshot(
            "active-status",
            lifecycle_status="active",
            closed_at=None,
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=None,
        ),
        "stopped_without_later_input": session_snapshot(
            "stopped-status",
            lifecycle_status="active",
            closed_at=None,
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=now - timedelta(minutes=5),
        ),
        "input_after_stop": session_snapshot(
            "input-after-stop",
            lifecycle_status="active",
            closed_at=None,
            last_input_at=now - timedelta(minutes=2),
            last_agent_stop_at=now - timedelta(minutes=5),
        ),
    }

    assert projections == snapshot


@pytest.mark.spec(_SPEC, "UC-SL23")
@pytest.mark.parametrize(
    ("event_type", "payload_data"),
    [
        (
            AgentHookEvents.AGENT_SESSION_START,
            {
                "session_id": "native-reviewer",
                "transcript_path": "/tmp/reviewer-transcript.jsonl",
            },
        ),
        (AgentHookEvents.AGENT_STOP, {"prompt": "review complete"}),
        (AgentHookEvents.TOOL_USE, {"tool_name": "Read"}),
        (AgentHookEvents.USER_PROMPT_SUBMIT, {"prompt": "please continue"}),
    ],
)
async def test_activity_hook_activates_initializing_session_for_live_lookup(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    cluster_event_bus: None,
    event_type: str,
    payload_data: dict[str, str],
) -> None:
    del cluster_event_bus
    slug = "reviewer-not-alive-regression"
    subdir = f"{WORKTREE_DIR}/{slug}"
    title = "/next-review-build reviewer-not-alive-regression"

    monkeypatch.setattr(coordinator_mod, "db", api.db)
    monkeypatch.setattr(coordinator_mod, "schedule_slow_work", lambda **_kwargs: None)
    monkeypatch.setattr(
        coordinator_mod.polling_coordinator,
        "schedule_session_projection",
        AsyncMock(return_value=None),
    )

    coordinator = AgentCoordinator(
        client=AsyncMock(),
        tts_manager=AsyncMock(),
    )
    monkeypatch.setattr(coordinator, "_extract_agent_output", AsyncMock(return_value=None))
    monkeypatch.setattr(coordinator, "_notify_session_listener", AsyncMock(return_value=None))
    monkeypatch.setattr(coordinator, "_forward_stop_to_initiator", AsyncMock(return_value=None))
    monkeypatch.setattr(coordinator, "_signal_projection_activity", AsyncMock(return_value=None))

    target = await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name="tc-target",
        last_input_origin=InputOrigin.TERMINAL.value,
        title=title,
        subdir=subdir,
        lifecycle_status="initializing",
        active_agent="claude",
        emit_session_started=False,
    )
    protected_statuses = {
        "headless": await api.db.create_session(
            computer_name="TestComputer",
            tmux_session_name="tc-headless",
            last_input_origin=InputOrigin.TERMINAL.value,
            title=title,
            subdir=subdir,
            lifecycle_status="headless",
            active_agent="claude",
            emit_session_started=False,
        ),
        "closing": await api.db.create_session(
            computer_name="TestComputer",
            tmux_session_name="tc-closing",
            last_input_origin=InputOrigin.TERMINAL.value,
            title=title,
            subdir=subdir,
            lifecycle_status="closing",
            active_agent="claude",
            emit_session_started=False,
        ),
        "closed": await api.db.create_session(
            computer_name="TestComputer",
            tmux_session_name="tc-closed",
            last_input_origin=InputOrigin.TERMINAL.value,
            title=title,
            subdir=subdir,
            lifecycle_status="closed",
            active_agent="claude",
            emit_session_started=False,
        ),
    }

    assert await find_live_session_for_slug(api.db, slug, "/next-review-build") is None

    for session in [target, *protected_statuses.values()]:
        await coordinator.handle_event(
            AgentEventContext(
                session_id=session.session_id,
                event_type=event_type,
                data=build_agent_payload(event_type, payload_data),
            )
        )

    repaired = await api.db.get_session(target.session_id)
    assert repaired is not None
    expected_native_fields = {}
    if event_type == AgentHookEvents.AGENT_SESSION_START:
        expected_native_fields = {
            "native_session_id": "native-reviewer",
            "native_log_file": "/tmp/reviewer-transcript.jsonl",
        }
    assert {
        "lifecycle_status": repaired.lifecycle_status,
        "native_session_id": repaired.native_session_id,
        "native_log_file": repaired.native_log_file,
    } == {
        "lifecycle_status": "active",
        "native_session_id": expected_native_fields.get("native_session_id"),
        "native_log_file": expected_native_fields.get("native_log_file"),
    }
    assert await find_live_session_for_slug(api.db, slug, "/next-review-build") == target.session_id

    for expected_status, session in protected_statuses.items():
        current = await api.db.get_session(session.session_id)
        assert current is not None
        assert current.lifecycle_status == expected_status


# ---------------------------------------------------------------------------
# 7. Session without identity or token is rejected
# ---------------------------------------------------------------------------


async def test_no_identity_no_token_rejected_in_multiuser(api: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """In multi-user mode, a caller with no headers at all gets 401."""
    monkeypatch.setattr(auth_mod, "_requires_terminal_login", lambda: True)

    resp = await api.get("/sessions")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 8. Session model default is None, not admin
# ---------------------------------------------------------------------------


async def test_session_model_default_is_none() -> None:
    """The Session dataclass must default human_role to None.
    This is the foundational invariant — no silent admin escalation.
    """
    session = Session(
        session_id="test",
        computer_name="test",
        tmux_session_name="test",
        title="test",
    )
    assert session.human_role is None


# ---------------------------------------------------------------------------
# 9. from_dict deserialization preserves None
# ---------------------------------------------------------------------------


async def test_from_dict_preserves_null_human_role() -> None:
    """Session.from_dict must not coerce missing human_role to admin."""
    session = Session.from_dict(
        {
            "session_id": "test",
            "computer_name": "test",
            "tmux_session_name": "test",
            "title": "test",
        }
    )
    assert session.human_role is None


# ---------------------------------------------------------------------------
# 10. Restricted role gets jailed to help-desk
# ---------------------------------------------------------------------------


@pytest.mark.spec(_SPEC, "UC-SL21")
async def test_restricted_role_jailed_to_help_desk(api: AsyncClient, tmp_path: Path, snapshot) -> None:
    """A session with human_role='newcomer' (non-admin, no system_role)
    should be jailed to the help-desk directory.
    """
    help_desk = tmp_path / "help-desk"
    help_desk.mkdir(parents=True, exist_ok=True)

    data = await _create_session(api, human_role="newcomer")
    session = await _get_session_from_db(api, data["session_id"])
    assert session.project_path is not None
    assert {"jailed_dir": Path(session.project_path).name} == snapshot


# ---------------------------------------------------------------------------
# 11. Worker-class commands dispatched via sessions/run are contained
# ---------------------------------------------------------------------------


async def _dispatch_run_session(
    api: AsyncClient,
    *,
    command: str,
    args: str,
    headers: dict[str, str] | None = None,
) -> Any:
    """POST /sessions/run and return the raw response."""
    return await api.post(
        "/sessions/run",
        json={
            "computer": "TestComputer",
            "command": command,
            "args": args,
            "project": "/tmp",
            "agent": "claude",
            "thinking_mode": "fast",
        },
        headers=headers or {},
    )


@pytest.mark.parametrize(
    ("command", "args", "expected_job", "expected_working_slug"),
    [
        (SlashCommand.NEXT_REVIEW_COMMITS, "abc123def4567890", JobRole.REVIEWER, None),
        (SlashCommand.NEXT_BUGS_FIX, "bug-slug", JobRole.FIXER, "bug-slug"),
        (SlashCommand.NEXT_CREATE_ART, "art-mood-board", JobRole.ARTIST, "art-mood-board"),
        (SlashCommand.NEXT_CREATE_HTML, "html-artifact", JobRole.FRONTENDER, "html-artifact"),
    ],
)
async def test_worker_class_dispatch_is_tagged_and_contained(
    api: AsyncClient,
    command: SlashCommand,
    args: str,
    expected_job: JobRole,
    expected_working_slug: str | None,
) -> None:
    """Worker-class command sessions are tagged as workers and cannot dispatch."""
    dispatch_resp = await _dispatch_run_session(api, command=f"/{command.value}", args=args)
    assert dispatch_resp.status_code == 200, f"dispatch failed: {dispatch_resp.text}"
    worker_session_id = dispatch_resp.json()["session_id"]

    worker = await _get_session_from_db(api, worker_session_id)
    assert worker is not None
    assert {
        "system_role": worker.system_role,
        "job": worker.job,
        "working_slug": worker.working_slug,
    } == {
        "system_role": ROLE_WORKER,
        "job": expected_job.value,
        "working_slug": expected_working_slug,
    }

    token = await api.db.issue_session_token(worker_session_id, f"system:{worker_session_id}", "admin")
    worker_headers = {"x-session-token": token}

    run_resp = await _dispatch_run_session(
        api,
        command=f"/{SlashCommand.NEXT_BUILD.value}",
        args="some-slug",
        headers=worker_headers,
    )
    assert run_resp.status_code == 403

    start_resp = await api.post(
        "/sessions",
        json={
            "computer": "TestComputer",
            "project_path": "/tmp",
            "agent": "claude",
            "thinking_mode": "fast",
            "title": "grandchild",
            "launch_kind": "empty",
        },
        headers=worker_headers,
    )
    assert start_resp.status_code == 403


async def test_adopted_human_session_keeps_sessions_run_clearance(
    api: AsyncClient, tmp_path: Path, cluster_event_bus: None
) -> None:
    """Regression for @input#symptom: a human/operator session that in-place
    adopts an unclaimed prepare/work todo must be recognized as the lane's
    orchestrator — not fall through the working_slug ⇒ worker fallback and lose
    /sessions/run clearance."""
    project = tmp_path / "human-adopt"
    project.mkdir()
    project_root = resolve_state_root(project)
    todos_db = await get_todos_db(project_root)
    slug = "human-adopted-slug"
    await todos_db.add_to_todo(slug, after=None)
    await todos_db.write_state(
        slug,
        TodoState(schema_version=5, kind="change", lifecycle_phase=LifecyclePhase.PREPARED.value).model_dump(
            exclude_none=True
        ),
    )

    session = await _create_session(api, human_role="admin", project_path=str(project))
    session_id = session["session_id"]

    adoption = await adopt_manual_lifecycle_session(str(project_root), slug, session_id, db=api.db)
    assert adoption.status is ManualLifecycleStatus.ADOPTED

    adopted = await _get_session_from_db(api, session_id)
    assert adopted.system_role == ROLE_ORCHESTRATOR
    assert adopted.system_role != ROLE_WORKER
    assert adopted.job == JobRole.WORK_ORCHESTRATOR.value

    token = await api.db.issue_session_token(session_id, f"system:{session_id}", "admin")
    run_resp = await _dispatch_run_session(
        api,
        command=f"/{SlashCommand.NEXT_REVIEW_COMMITS.value}",
        args="abc123def4567890",
        headers={"x-session-token": token},
    )
    assert run_resp.status_code == 200, run_resp.text


# ---------------------------------------------------------------------------
# Lifecycle driver-start dedup — create-door boundary
# ---------------------------------------------------------------------------


async def _seed_driven_todo(
    api: AsyncClient,
    project_root: Path,
    slug: str,
    holder_id: str,
    *,
    as_orchestrator: bool,
) -> None:
    """Seed a live driver for ``slug`` in ``project_root``: a live holder session
    plus a todo whose ``active_runner`` points at it. An orchestrator holder also
    registers as the registry owner; a worker holder is seen only via active_runner.
    """
    await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name=f"tmux-{holder_id}",
        last_input_origin="terminal",
        title=f"holder {slug}",
        session_id=holder_id,
        system_role=ROLE_ORCHESTRATOR if as_orchestrator else ROLE_WORKER,
        project_path=str(project_root),
        working_slug=slug,
        emit_session_started=False,
    )
    todos_db = await get_todos_db(project_root)
    await todos_db.add_to_todo(slug, after=None)
    await todos_db.write_state(
        slug,
        TodoState(
            schema_version=5,
            kind="change",
            lifecycle_phase=LifecyclePhase.PREPARED.value,
            active_runner=holder_id,
        ).model_dump(exclude_none=True),
    )


async def _bound_session_ids(api: AsyncClient, slug: str) -> list[str]:
    sessions = await api.db.list_sessions(include_closed=True)
    return [s.session_id for s in sessions if s.working_slug == slug]


async def test_run_session_refuses_duplicate_orchestrator_driver(api: AsyncClient, tmp_path: Path) -> None:
    project = tmp_path / "orch-conflict"
    project.mkdir()
    holder = "holder-orch"
    await _seed_driven_todo(api, resolve_state_root(project), "orch-slug", holder, as_orchestrator=True)

    resp = await api.post(
        "/sessions/run",
        json={
            "computer": "TestComputer",
            "command": "/next-work",
            "args": "orch-slug",
            "project": str(project),
            "agent": "claude",
        },
    )

    assert resp.status_code == 409, resp.text
    assert holder in resp.text
    assert await _bound_session_ids(api, "orch-slug") == [holder]


async def test_run_session_refuses_duplicate_task_runner(api: AsyncClient, tmp_path: Path) -> None:
    project = tmp_path / "task-conflict"
    project.mkdir()
    holder = "holder-task"
    await _seed_driven_todo(api, resolve_state_root(project), "task-slug", holder, as_orchestrator=False)

    resp = await api.post(
        "/sessions/run",
        json={
            "computer": "TestComputer",
            "command": "/next-run-task",
            "args": "task-slug",
            "project": str(project),
            "agent": "claude",
        },
    )

    assert resp.status_code == 409, resp.text
    assert holder in resp.text
    assert await _bound_session_ids(api, "task-slug") == [holder]


async def test_run_session_allows_worker_child_spawn_for_held_slug(api: AsyncClient, tmp_path: Path) -> None:
    project = tmp_path / "worker-allow"
    project.mkdir()
    holder = "holder-w"
    await _seed_driven_todo(api, resolve_state_root(project), "held-slug", holder, as_orchestrator=True)

    resp = await api.post(
        "/sessions/run",
        json={
            "computer": "TestComputer",
            "command": "/next-build",
            "args": "held-slug",
            "project": str(project),
            "agent": "claude",
        },
    )

    assert resp.status_code == 200, resp.text
    bound = await _bound_session_ids(api, "held-slug")
    assert holder in bound
    assert len(bound) == 2


async def test_create_session_refuses_duplicate_driver_on_worktree(api: AsyncClient, tmp_path: Path) -> None:
    project = tmp_path / "tree-conflict"
    project.mkdir()
    holder = "holder-tree"
    await _seed_driven_todo(api, resolve_state_root(project), "tree-slug", holder, as_orchestrator=True)

    resp = await api.post(
        "/sessions",
        json={
            "computer": "TestComputer",
            "project_path": str(project),
            "agent": "claude",
            "thinking_mode": "fast",
            "subdir": f"{WORKTREE_DIR}/tree-slug",
            "message": "/next-work tree-slug",
        },
    )

    assert resp.status_code == 409, resp.text
    assert holder in resp.text
    assert await _bound_session_ids(api, "tree-slug") == [holder]
