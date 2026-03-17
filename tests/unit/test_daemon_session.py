"""Characterization tests for teleclaude.daemon_session."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import teleclaude.daemon_session as daemon_session
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
        self.command_service = SimpleNamespace()
        self.headless_snapshot_service = SimpleNamespace(send_snapshot=AsyncMock())
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
async def test_bootstrap_injects_system_role_into_tmux_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """When a session has system_role in metadata, it reaches the tmux env."""
    from teleclaude.constants import ROLE_INTEGRATOR
    from teleclaude.core.models import SessionMetadata

    daemon_inst = _TestDaemon()
    captured_env: dict[str, str] = {}

    session = SimpleNamespace(
        session_id="sess-role",
        tmux_session_name="tc_sess-role",
        project_path="/tmp/proj",
        subdir=None,
        lifecycle_status="initializing",
        session_metadata=SessionMetadata(system_role=ROLE_INTEGRATOR, job="integrator"),
        principal=None,
        human_email=None,
        human_role=None,
    )

    async def fake_ensure_tmux(*, name: str, working_dir: str, session_id: str, env_vars: dict[str, str]) -> bool:
        captured_env.update(env_vars)
        return True

    db_stub = SimpleNamespace(
        get_session=AsyncMock(return_value=session),
        get_voice=AsyncMock(return_value=None),
        issue_session_token=AsyncMock(return_value="tok"),
        update_session=AsyncMock(),
    )
    monkeypatch.setattr(daemon_session, "db", db_stub)
    monkeypatch.setattr(daemon_session, "resolve_session_principal", lambda s: ("system:sess-role", "admin"))
    monkeypatch.setattr(daemon_session, "resolve_working_dir", lambda p, s: "/tmp/proj")
    monkeypatch.setattr(daemon_session, "tmux_bridge", SimpleNamespace(ensure_tmux_session=fake_ensure_tmux))
    monkeypatch.setattr(daemon_inst, "_start_polling_for_session", AsyncMock())

    await daemon_inst._bootstrap_session_resources("sess-role", None)

    assert "TELECLAUDE_SYSTEM_ROLE" in captured_env
    assert captured_env["TELECLAUDE_SYSTEM_ROLE"] == ROLE_INTEGRATOR


@pytest.mark.unit
async def test_bootstrap_omits_system_role_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """When a session has no system_role, TELECLAUDE_SYSTEM_ROLE is not set."""
    daemon_inst = _TestDaemon()
    captured_env: dict[str, str] = {}

    session = SimpleNamespace(
        session_id="sess-plain",
        tmux_session_name="tc_sess-plain",
        project_path="/tmp/proj",
        subdir=None,
        lifecycle_status="initializing",
        session_metadata=None,
        principal=None,
        human_email=None,
        human_role=None,
    )

    async def fake_ensure_tmux(*, name: str, working_dir: str, session_id: str, env_vars: dict[str, str]) -> bool:
        captured_env.update(env_vars)
        return True

    db_stub = SimpleNamespace(
        get_session=AsyncMock(return_value=session),
        get_voice=AsyncMock(return_value=None),
        issue_session_token=AsyncMock(return_value="tok"),
        update_session=AsyncMock(),
    )
    monkeypatch.setattr(daemon_session, "db", db_stub)
    monkeypatch.setattr(daemon_session, "resolve_session_principal", lambda s: ("system:sess-plain", "admin"))
    monkeypatch.setattr(daemon_session, "resolve_working_dir", lambda p, s: "/tmp/proj")
    monkeypatch.setattr(daemon_session, "tmux_bridge", SimpleNamespace(ensure_tmux_session=fake_ensure_tmux))
    monkeypatch.setattr(daemon_inst, "_start_polling_for_session", AsyncMock())

    await daemon_inst._bootstrap_session_resources("sess-plain", None)

    assert "TELECLAUDE_SYSTEM_ROLE" not in captured_env


@pytest.mark.unit
async def test_wait_for_agent_prompt_ready_uses_marker_when_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the agent has a known prompt marker and it appears in output, returns True immediately."""
    daemon_inst = _TestDaemon()
    session = SimpleNamespace(tmux_session_name="tc_test")

    marker = daemon_session.AGENT_PROMPT_READY_MARKERS["gemini"]
    pane_with_marker = f"some startup text\n{marker}\nmore text"

    monkeypatch.setattr(
        daemon_inst,
        "_wait_for_output_contains",
        AsyncMock(return_value=(True, pane_with_marker)),
    )
    stable_mock = AsyncMock(return_value=(True, pane_with_marker))
    monkeypatch.setattr(daemon_inst, "_wait_for_output_stable", stable_mock)

    found, _tail = await daemon_inst._wait_for_agent_prompt_ready(session, "gemini", 15.0, 1.0)

    assert found is True
    assert marker in _tail
    stable_mock.assert_not_awaited()


@pytest.mark.unit
async def test_wait_for_agent_prompt_ready_falls_back_to_inactivity_when_marker_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the agent marker is not found within timeout, falls back to inactivity detection."""
    daemon_inst = _TestDaemon()
    session = SimpleNamespace(tmux_session_name="tc_test")

    monkeypatch.setattr(
        daemon_inst,
        "_wait_for_output_contains",
        AsyncMock(return_value=(False, "startup text without marker")),
    )
    stable_mock = AsyncMock(return_value=(True, "stabilized output"))
    monkeypatch.setattr(daemon_inst, "_wait_for_output_stable", stable_mock)

    found, _tail = await daemon_inst._wait_for_agent_prompt_ready(session, "gemini", 15.0, 1.0)

    assert found is True
    stable_mock.assert_awaited_once()


@pytest.mark.unit
async def test_wait_for_agent_prompt_ready_uses_inactivity_for_unknown_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When agent has no known marker, uses inactivity detection directly."""
    daemon_inst = _TestDaemon()
    session = SimpleNamespace(tmux_session_name="tc_test")

    contains_mock = AsyncMock(return_value=(True, "output"))
    monkeypatch.setattr(daemon_inst, "_wait_for_output_contains", contains_mock)
    stable_mock = AsyncMock(return_value=(False, "timeout output"))
    monkeypatch.setattr(daemon_inst, "_wait_for_output_stable", stable_mock)

    found, _tail = await daemon_inst._wait_for_agent_prompt_ready(session, "unknown_agent", 10.0, 1.0)

    assert found is False
    contains_mock.assert_not_awaited()
    stable_mock.assert_awaited_once()


@pytest.mark.unit
async def test_wait_for_agent_prompt_ready_passes_correct_marker_to_contains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each agent's known marker is passed verbatim to _wait_for_output_contains."""
    daemon_inst = _TestDaemon()
    session = SimpleNamespace(tmux_session_name="tc_test")

    captured_needles: list[str] = []

    async def fake_contains(s: object, needle: str, timeout: float) -> tuple[bool, str]:
        captured_needles.append(needle)
        return True, f"output with {needle}"

    monkeypatch.setattr(daemon_inst, "_wait_for_output_contains", fake_contains)
    monkeypatch.setattr(daemon_inst, "_wait_for_output_stable", AsyncMock())

    for agent_name, expected_marker in daemon_session.AGENT_PROMPT_READY_MARKERS.items():
        captured_needles.clear()
        await daemon_inst._wait_for_agent_prompt_ready(session, agent_name, 15.0, 1.0)
        assert captured_needles == [expected_marker], f"Wrong marker for {agent_name}"


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
