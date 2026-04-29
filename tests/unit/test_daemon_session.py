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
from teleclaude.core.events import SessionLifecycleContext, TeleClaudeEvents


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
    assert "world" in summary.before_snippet
    assert "there" in summary.after_snippet


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
@pytest.mark.asyncio
@pytest.mark.parametrize(("agent_name", "thinking_mode"), [("claude", "slow"), ("gemini", "fast"), ("codex", "fast")])
async def test_handle_agent_then_message_passes_session_and_constants_to_detector(
    monkeypatch: pytest.MonkeyPatch,
    agent_name: str,
    thinking_mode: str,
) -> None:
    daemon_inst = _TestDaemon()
    session = MagicMock(
        session_id="sess-1",
        tmux_session_name="tc_sess-1",
        project_path="/tmp",
        subdir="",
        active_agent=agent_name,
    )
    db_stub = SimpleNamespace(
        update_session=AsyncMock(),
        get_session=AsyncMock(return_value=session),
        update_last_activity=AsyncMock(),
    )
    ready_mock = AsyncMock(return_value=(True, "prompt > "))
    emit_mock = MagicMock()
    monkeypatch.setattr(daemon_session, "db", db_stub)
    monkeypatch.setattr(daemon_session, "wait_for_agent_ready", ready_mock, raising=False)
    monkeypatch.setattr(daemon_session.event_bus, "emit", emit_mock)
    monkeypatch.setattr(daemon_session.tmux_io, "is_process_running", AsyncMock(return_value=True))
    monkeypatch.setattr(daemon_session.tmux_io, "process_text", AsyncMock(return_value=True))
    monkeypatch.setattr(daemon_session.tmux_io, "wrap_bracketed_paste", lambda text, active_agent: text)
    monkeypatch.setattr(daemon_session, "resolve_working_dir", lambda project_path, subdir: project_path)
    monkeypatch.setattr(daemon_inst, "_poll_and_send_output", AsyncMock())
    monkeypatch.setattr(daemon_inst, "_confirm_command_acceptance", AsyncMock(return_value=True))

    result = await daemon_inst._handle_agent_then_message(
        "sess-1", agent_name=agent_name, thinking_mode=thinking_mode, message="hello"
    )

    assert result["status"] == "success"
    ready_mock.assert_awaited_once_with(
        agent_name,
        session,
        daemon_session.AGENT_PROMPT_READY_TIMEOUT_S,
        daemon_session.AGENT_START_STABILIZE_QUIET_S,
    )
    assert emit_mock.call_args_list[0].args[0] == TeleClaudeEvents.AGENT_READY
    assert emit_mock.call_args_list[0].args[1].session_id == "sess-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_agent_then_message_returns_error_when_readiness_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon_inst = _TestDaemon()
    session = MagicMock(session_id="sess-1", tmux_session_name="tc_sess-1")
    db_stub = SimpleNamespace(
        update_session=AsyncMock(),
        get_session=AsyncMock(return_value=session),
        update_last_activity=AsyncMock(),
    )
    ready_mock = AsyncMock(return_value=(False, "still loading"))
    emit_mock = MagicMock()
    terminate_mock = AsyncMock()
    process_text_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(daemon_session, "db", db_stub)
    monkeypatch.setattr(daemon_session, "wait_for_agent_ready", ready_mock, raising=False)
    monkeypatch.setattr(daemon_session.event_bus, "emit", emit_mock)
    monkeypatch.setattr(
        daemon_session.session_cleanup,
        "terminate_session",
        terminate_mock,
    )
    monkeypatch.setattr(daemon_session.tmux_io, "process_text", process_text_mock)

    result = await daemon_inst._handle_agent_then_message(
        "sess-1", agent_name="claude", thinking_mode="slow", message="hello"
    )

    assert result["status"] == "error"
    assert "kept alive" in result["message"]
    assert emit_mock.call_args_list[0].args[0] == TeleClaudeEvents.AGENT_READINESS_TIMEOUT
    assert emit_mock.call_args_list[0].args[1].session_id == "sess-1"
    # Session is kept alive on timeout — no terminate, no message injection
    terminate_mock.assert_not_awaited()
    process_text_mock.assert_not_awaited()


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
    monkeypatch.setattr(daemon_session.event_bus, "emit", lambda event, context: emitted.append((event, context)))

    await daemon_instance._handle_session_close_requested(
        "session_close_requested",
        SessionLifecycleContext(session_id="sess-1"),
    )

    terminate_session.assert_awaited_once()
    db_stub.update_session.assert_awaited_once_with("sess-1", lifecycle_status="active")
    assert emitted[0][0] == TeleClaudeEvents.SESSION_STATUS
    assert emitted[0][1].status == "error"
    assert emitted[0][1].reason == "close_failed"
