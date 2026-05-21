"""Characterization tests for teleclaude.daemon_session."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import teleclaude.core.session_bootstrap as session_bootstrap
import teleclaude.daemon_session as daemon_session
from teleclaude.constants import ROLE_INTEGRATOR
from teleclaude.core.agent_readiness import WINNER_HOOK, WINNER_PANE, ReadinessRaceResult
from teleclaude.core.agents import AgentName
from teleclaude.core.events import AgentHookEvents, SessionLifecycleContext, TeleClaudeEvents


class _TestDaemon(daemon_session._DaemonSessionMixin):
    def __init__(self) -> None:
        self.shutdown_event = asyncio.Event()
        self._background_tasks: set[asyncio.Task[object]] = set()
        self._session_outbox_queues: dict[
            str, Any
        ] = {}  # guard: loose-dict - Test helper payloads intentionally vary by scenario.
        self._session_outbox_workers: dict[str, asyncio.Task[None]] = {}
        self._hook_outbox_claim_paused_sessions: set[str] = set()
        self.client = SimpleNamespace(send_message=AsyncMock())
        self.agent_coordinator = SimpleNamespace(handle_event=AsyncMock())
        self.command_service = SimpleNamespace(start_agent=AsyncMock())
        self.output_poller = SimpleNamespace()
        self.tracked: list[tuple[asyncio.Task[object], str]] = []

    def _track_background_task(self, task: asyncio.Task[object], label: str) -> None:
        self.tracked.append((task, label))

    async def _poll_and_send_output(
        self,
        session_id: str,
        tmux_session_name: str,
    ) -> None:  # pragma: no cover - unused in these tests
        raise NotImplementedError

    async def _start_polling_for_session(
        self,
        session_id: str,
        tmux_session_name: str,
    ) -> None:  # pragma: no cover - unused in these tests
        raise NotImplementedError


def test_summarize_output_change_reports_lengths_and_diff_boundary() -> None:
    summary = daemon_session._DaemonSessionMixin._summarize_output_change("hello world", "hello there")

    assert summary.changed is True
    assert summary.before_len == 11
    assert summary.after_len == 11
    assert summary.diff_index == 6
    assert summary.before_snippet
    assert summary.after_snippet


@pytest.mark.unit
async def test_handle_session_closed_cleans_state_and_cancels_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon_instance = _TestDaemon()
    session_id = "sess-1"
    cleaned_ids: list[str] = []
    mirror_handler = AsyncMock()
    worker = asyncio.create_task(asyncio.sleep(3600))
    daemon_instance._session_outbox_queues[session_id] = object()
    daemon_instance._session_outbox_workers[session_id] = worker
    daemon_instance._hook_outbox_claim_paused_sessions.add(session_id)
    monkeypatch.setattr(
        daemon_session.polling_coordinator,
        "_cleanup_codex_input_state",
        cleaned_ids.append,
    )
    monkeypatch.setattr(daemon_session, "handle_mirror_session_closed", mirror_handler)

    await daemon_instance._handle_session_closed("session_closed", SessionLifecycleContext(session_id=session_id))

    assert session_id not in daemon_instance._session_outbox_queues
    assert session_id not in daemon_instance._session_outbox_workers
    assert session_id not in daemon_instance._hook_outbox_claim_paused_sessions
    assert worker.cancelled() is True
    assert cleaned_ids == [session_id]
    mirror_handler.assert_awaited_once()


@pytest.mark.unit
async def test_bootstrap_writes_system_role_to_identity_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When a session has system_role in metadata, it is written to the identity file."""
    daemon_inst = _TestDaemon()
    identity_calls: list[dict[str, str]] = []

    session = SimpleNamespace(
        session_id="sess-role",
        tmux_session_name="tc_sess-role",
        project_path="/tmp/proj",
        subdir=None,
        lifecycle_status="initializing",
        system_role=ROLE_INTEGRATOR,
        job="integrator",
        principal=None,
        human_email=None,
        human_role=None,
    )

    async def fake_ensure_tmux(*, name: str, working_dir: str, session_id: str, env_vars: dict[str, str]) -> bool:
        return True

    db_stub = SimpleNamespace(
        get_session=AsyncMock(return_value=session),
        get_voice=AsyncMock(return_value=None),
        issue_session_token=AsyncMock(return_value="tok"),
        update_session=AsyncMock(),
    )
    monkeypatch.setattr(daemon_session, "db", db_stub)
    monkeypatch.setattr(session_bootstrap, "db", db_stub)
    monkeypatch.setattr(session_bootstrap, "resolve_session_principal", lambda s: ("system:sess-role", "admin"))
    monkeypatch.setattr(daemon_session, "resolve_working_dir", lambda p, s: "/tmp/proj")
    monkeypatch.setattr(
        session_bootstrap,
        "tmux_bridge",
        SimpleNamespace(ensure_tmux_session=fake_ensure_tmux, get_session_tmpdir=lambda sid: tmp_path),
    )
    monkeypatch.setattr(
        session_bootstrap,
        "write_session_identity_to",
        lambda **kw: identity_calls.append(kw),
    )
    monkeypatch.setattr(daemon_inst, "_start_polling_for_session", AsyncMock())

    await daemon_inst._bootstrap_session_resources("sess-role", None)

    assert len(identity_calls) == 1
    assert identity_calls[0]["session_id"] == "sess-role"
    assert identity_calls[0]["system_role"] == ROLE_INTEGRATOR
    assert identity_calls[0]["session_token"] == "tok"


@pytest.mark.unit
async def test_bootstrap_writes_none_system_role_when_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When a session has no system_role, None is written to the identity file."""
    daemon_inst = _TestDaemon()
    identity_calls: list[dict[str, str]] = []

    session = SimpleNamespace(
        session_id="sess-plain",
        tmux_session_name="tc_sess-plain",
        project_path="/tmp/proj",
        subdir=None,
        lifecycle_status="initializing",
        system_role=None,
        job=None,
        principal=None,
        human_email=None,
        human_role=None,
    )

    async def fake_ensure_tmux(*, name: str, working_dir: str, session_id: str, env_vars: dict[str, str]) -> bool:
        return True

    db_stub = SimpleNamespace(
        get_session=AsyncMock(return_value=session),
        get_voice=AsyncMock(return_value=None),
        issue_session_token=AsyncMock(return_value="tok"),
        update_session=AsyncMock(),
    )
    monkeypatch.setattr(daemon_session, "db", db_stub)
    monkeypatch.setattr(session_bootstrap, "db", db_stub)
    monkeypatch.setattr(session_bootstrap, "resolve_session_principal", lambda s: ("system:sess-plain", "admin"))
    monkeypatch.setattr(daemon_session, "resolve_working_dir", lambda p, s: "/tmp/proj")
    monkeypatch.setattr(
        session_bootstrap,
        "tmux_bridge",
        SimpleNamespace(ensure_tmux_session=fake_ensure_tmux, get_session_tmpdir=lambda sid: tmp_path),
    )
    monkeypatch.setattr(
        session_bootstrap,
        "write_session_identity_to",
        lambda **kw: identity_calls.append(kw),
    )
    monkeypatch.setattr(daemon_inst, "_start_polling_for_session", AsyncMock())

    await daemon_inst._bootstrap_session_resources("sess-plain", None)

    assert len(identity_calls) == 1
    assert identity_calls[0]["system_role"] is None


@pytest.mark.unit
async def test_bootstrap_skips_token_for_human_principal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Human-initiated sessions (human:<email> principal) do not receive a token."""
    daemon_inst = _TestDaemon()
    identity_calls: list[dict[str, str]] = []

    session = SimpleNamespace(
        session_id="sess-human",
        tmux_session_name="tc_sess-human",
        project_path="/tmp/proj",
        subdir=None,
        lifecycle_status="initializing",
        system_role=None,
        job=None,
        principal=None,
        human_email="maurice@instrukt.ai",
        human_role="admin",
    )

    async def fake_ensure_tmux(*, name: str, working_dir: str, session_id: str, env_vars: dict[str, str]) -> bool:
        return True

    db_stub = SimpleNamespace(
        get_session=AsyncMock(return_value=session),
        get_voice=AsyncMock(return_value=None),
        issue_session_token=AsyncMock(return_value="tok"),
        update_session=AsyncMock(),
    )
    monkeypatch.setattr(daemon_session, "db", db_stub)
    monkeypatch.setattr(session_bootstrap, "db", db_stub)
    monkeypatch.setattr(
        session_bootstrap, "resolve_session_principal", lambda s: ("human:maurice@instrukt.ai", "admin")
    )
    monkeypatch.setattr(daemon_session, "resolve_working_dir", lambda p, s: "/tmp/proj")
    monkeypatch.setattr(
        session_bootstrap,
        "tmux_bridge",
        SimpleNamespace(ensure_tmux_session=fake_ensure_tmux, get_session_tmpdir=lambda sid: tmp_path),
    )
    monkeypatch.setattr(
        session_bootstrap,
        "write_session_identity_to",
        lambda **kw: identity_calls.append(kw),
    )
    monkeypatch.setattr(daemon_inst, "_start_polling_for_session", AsyncMock())

    await daemon_inst._bootstrap_session_resources("sess-human", None)

    assert len(identity_calls) == 1
    assert identity_calls[0]["session_token"] is None
    db_stub.issue_session_token.assert_not_called()


@pytest.mark.unit
async def test_bootstrap_writes_human_role_without_email(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Headless human sessions have human_role but no human_email — human_role must still be written."""
    daemon_inst = _TestDaemon()
    identity_calls: list[dict[str, str]] = []

    session = SimpleNamespace(
        session_id="sess-headless-human",
        tmux_session_name="tc_sess-headless",
        project_path="/tmp/proj",
        subdir=None,
        lifecycle_status="headless",
        system_role=None,
        job=None,
        principal=None,
        human_email=None,
        human_role="admin",
    )

    async def fake_ensure_tmux(*, name: str, working_dir: str, session_id: str, env_vars: dict[str, str]) -> bool:
        return True

    db_stub = SimpleNamespace(
        get_session=AsyncMock(return_value=session),
        get_voice=AsyncMock(return_value=None),
        issue_session_token=AsyncMock(return_value="tok"),
        update_session=AsyncMock(),
    )
    monkeypatch.setattr(daemon_session, "db", db_stub)
    monkeypatch.setattr(session_bootstrap, "db", db_stub)
    monkeypatch.setattr(
        session_bootstrap, "resolve_session_principal", lambda s: ("system:sess-headless-human", "admin")
    )
    monkeypatch.setattr(daemon_session, "resolve_working_dir", lambda p, s: "/tmp/proj")
    monkeypatch.setattr(
        session_bootstrap,
        "tmux_bridge",
        SimpleNamespace(ensure_tmux_session=fake_ensure_tmux, get_session_tmpdir=lambda sid: tmp_path),
    )
    monkeypatch.setattr(
        session_bootstrap,
        "write_session_identity_to",
        lambda **kw: identity_calls.append(kw),
    )
    monkeypatch.setattr(daemon_inst, "_start_polling_for_session", AsyncMock())

    await daemon_inst._bootstrap_session_resources("sess-headless-human", None)

    assert len(identity_calls) == 1
    assert identity_calls[0]["human_role"] == "admin"


@pytest.mark.unit
async def test_handle_session_close_requested_restores_active_status_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon_instance = _TestDaemon()
    session = SimpleNamespace(closed_at=None)
    db_stub = SimpleNamespace(
        get_session=AsyncMock(side_effect=[session, session]),
        update_session=AsyncMock(),
    )
    terminate_session = AsyncMock(side_effect=RuntimeError("boom"))
    emitted: list[tuple[str, object]] = []
    monkeypatch.setattr(daemon_session, "db", db_stub)
    monkeypatch.setattr(daemon_session.session_cleanup, "terminate_session", terminate_session)
    monkeypatch.setattr(
        daemon_session,
        "serialize_status_event",
        lambda **_kwargs: SimpleNamespace(message_intent="status", delivery_scope="session"),
    )
    monkeypatch.setattr(
        daemon_session.event_bus,
        "emit",
        lambda event, context, **_kwargs: emitted.append((event, context)),
    )

    await daemon_instance._handle_session_close_requested(
        "session_close_requested",
        SessionLifecycleContext(session_id="sess-1"),
    )

    terminate_session.assert_awaited_once()
    db_stub.update_session.assert_awaited_once_with("sess-1", lifecycle_status="active")
    assert emitted[0][0] == TeleClaudeEvents.SESSION_STATUS
    assert emitted[0][1].status == "error"
    assert emitted[0][1].reason == "close_failed"


def _make_session_for_start(agent: str) -> SimpleNamespace:
    return SimpleNamespace(
        session_id=f"sess-{agent}",
        project_path=f"/work/{agent}",
        tmux_session_name=f"tc-{agent}",
    )


@pytest.mark.unit
async def test_await_agent_start_readiness_delegates_to_race_for_non_codex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The cold-launch wrapper must forward the agent name to the race helper
    # for every adapter. Prior to this delivery, Claude/Gemini bypassed the
    # race entirely; the test pins the lifted-conditional behavior.
    daemon_inst = _TestDaemon()
    session = _make_session_for_start(AgentName.CLAUDE.value)
    loop = asyncio.get_event_loop()
    ready_future: asyncio.Future[None] = loop.create_future()
    ready_future.set_result(None)

    race_mock = AsyncMock(return_value=ReadinessRaceResult(winner=WINNER_HOOK, elapsed_s=0.05))
    monkeypatch.setattr(daemon_session, "race_for_readiness", race_mock)
    info_mock = MagicMock()
    monkeypatch.setattr(daemon_session.logger, "info", info_mock)

    await daemon_inst._await_agent_start_readiness(
        agent_name=AgentName.CLAUDE.value,
        session=session,
        session_id=session.session_id,
        ready_future=ready_future,
    )

    race_mock.assert_awaited_once()
    call_kwargs = race_mock.await_args.kwargs
    assert call_kwargs["agent_name"] == AgentName.CLAUDE.value
    assert call_kwargs["session"] is session
    assert call_kwargs["ready_future"] is ready_future
    assert call_kwargs["pane_task_name"]
    assert call_kwargs["hook_task_name"]

    info_mock.assert_called_once()
    assert info_mock.call_args.args[0]
    log_kwargs = info_mock.call_args.kwargs
    assert log_kwargs["winner"] == WINNER_HOOK
    assert log_kwargs["adapter"] == AgentName.CLAUDE.value
    assert log_kwargs["phase"]
    assert log_kwargs["hook_lag_ms"] == 50


@pytest.mark.unit
async def test_await_agent_start_readiness_skips_synthesis_for_non_codex_pane_win(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When Claude/Gemini wins via the pane detector, no synthetic
    # session_start event should fire — the real hook will arrive late but
    # it will arrive, and downstream consumers must not see a duplicate.
    daemon_inst = _TestDaemon()
    daemon_inst.agent_coordinator = SimpleNamespace(handle_session_start=AsyncMock())
    session = _make_session_for_start(AgentName.GEMINI.value)
    loop = asyncio.get_event_loop()
    ready_future: asyncio.Future[None] = loop.create_future()

    race_mock = AsyncMock(return_value=ReadinessRaceResult(winner=WINNER_PANE, elapsed_s=0.8, tail="x"))
    monkeypatch.setattr(daemon_session, "race_for_readiness", race_mock)
    monkeypatch.setattr(daemon_session.logger, "info", MagicMock())

    await daemon_inst._await_agent_start_readiness(
        agent_name=AgentName.GEMINI.value,
        session=session,
        session_id=session.session_id,
        ready_future=ready_future,
    )

    daemon_inst.agent_coordinator.handle_session_start.assert_not_awaited()


@pytest.mark.unit
async def test_await_agent_start_readiness_synthesizes_session_start_for_codex_pane_win(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Codex's native SessionStart hook does not fire on cold thread_spawn.
    # When the pane detector wins for Codex, the wrapper must dispatch a
    # synthetic AGENT_SESSION_START event so downstream subscribers stay
    # consistent. Other adapters do NOT get synthesis.
    daemon_inst = _TestDaemon()
    session = _make_session_for_start(AgentName.CODEX.value)
    loop = asyncio.get_event_loop()
    ready_future: asyncio.Future[None] = loop.create_future()

    async def _resolve_future_on_synthesis(_ctx: object) -> None:
        # Simulate the real coordinator's downstream emit of AGENT_READY,
        # which the wrapper re-awaits via the shielded ready_future.
        if not ready_future.done():
            ready_future.set_result(None)

    handle_session_start = AsyncMock(side_effect=_resolve_future_on_synthesis)
    daemon_inst.agent_coordinator = SimpleNamespace(handle_session_start=handle_session_start)

    race_mock = AsyncMock(return_value=ReadinessRaceResult(winner=WINNER_PANE, elapsed_s=0.9, tail="x"))
    monkeypatch.setattr(daemon_session, "race_for_readiness", race_mock)
    monkeypatch.setattr(daemon_session.logger, "info", MagicMock())

    await daemon_inst._await_agent_start_readiness(
        agent_name=AgentName.CODEX.value,
        session=session,
        session_id=session.session_id,
        ready_future=ready_future,
    )

    handle_session_start.assert_awaited_once()
    synthetic_ctx = handle_session_start.await_args.args[0]
    assert synthetic_ctx.event_type == AgentHookEvents.AGENT_SESSION_START
    assert synthetic_ctx.session_id == session.session_id
