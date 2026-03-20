"""Characterization tests for teleclaude.daemon_session."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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
        self.command_service = SimpleNamespace(start_agent=AsyncMock())
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
async def test_bootstrap_skips_token_for_human_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Human-initiated sessions (human:<email> principal) do not receive a token."""
    daemon_inst = _TestDaemon()
    captured_env: dict[str, str] = {}

    session = SimpleNamespace(
        session_id="sess-human",
        tmux_session_name="tc_sess-human",
        project_path="/tmp/proj",
        subdir=None,
        lifecycle_status="initializing",
        session_metadata=None,
        principal=None,
        human_email="maurice@instrukt.ai",
        human_role="admin",
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
    monkeypatch.setattr(daemon_session, "resolve_session_principal", lambda s: ("human:maurice@instrukt.ai", "admin"))
    monkeypatch.setattr(daemon_session, "resolve_working_dir", lambda p, s: "/tmp/proj")
    monkeypatch.setattr(daemon_session, "tmux_bridge", SimpleNamespace(ensure_tmux_session=fake_ensure_tmux))
    monkeypatch.setattr(daemon_inst, "_start_polling_for_session", AsyncMock())

    await daemon_inst._bootstrap_session_resources("sess-human", None)

    assert "TELEC_SESSION_TOKEN" not in captured_env
    db_stub.issue_session_token.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_agent_then_message_passes_session_and_constants_to_detector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon_inst = _TestDaemon()
    session = MagicMock(
        session_id="sess-1",
        tmux_session_name="tc_sess-1",
        project_path="/tmp",
        subdir="",
        active_agent="claude",
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

    result = await daemon_inst._handle_agent_then_message("sess-1", ["claude", "slow", "hello"])

    assert result["status"] == "success"
    ready_mock.assert_awaited_once_with(
        "claude",
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

    result = await daemon_inst._handle_agent_then_message("sess-1", ["claude", "slow", "hello"])

    assert result["status"] == "error"
    assert emit_mock.call_args_list[0].args[0] == TeleClaudeEvents.AGENT_READINESS_TIMEOUT
    assert emit_mock.call_args_list[0].args[1].session_id == "sess-1"
    terminate_mock.assert_awaited_once_with(
        "sess-1",
        daemon_inst.client,
        reason="agent_readiness_timeout",
        session=session,
    )
    daemon_inst.client.send_message.assert_awaited_once()
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


class TestDaemonSessionReadinessSpec:
    """Test that _handle_agent_then_message uses the new detector and emits events."""

    @pytest.mark.asyncio
    async def test_handle_agent_then_message_emits_ready_event(self, monkeypatch):
        """Test that _handle_agent_then_message calls detector and emits AGENT_READY."""
        daemon = _TestDaemon()
        session_id = "sess-1"

        # Mock database and session
        mock_db = AsyncMock()
        monkeypatch.setattr("teleclaude.daemon_session.db", mock_db)

        # Mock wait_for_agent_ready from the new module
        mock_ready = AsyncMock(return_value=(True, "prompt > "))
        # We'll need to patch wherever wait_for_agent_ready is imported in daemon_session
        # Using raising=False since it's not yet imported there
        monkeypatch.setattr("teleclaude.daemon_session.wait_for_agent_ready", mock_ready, raising=False)

        mock_emit = MagicMock()
        monkeypatch.setattr("teleclaude.daemon_session.event_bus.emit", mock_emit)

        mock_tmux = SimpleNamespace(
            is_process_running=AsyncMock(return_value=True),
            process_text=AsyncMock(return_value=True),
            wrap_bracketed_paste=lambda text, active_agent: text,
        )
        monkeypatch.setattr("teleclaude.daemon_session.tmux_io", mock_tmux)
        monkeypatch.setattr(daemon, "_poll_and_send_output", AsyncMock())
        monkeypatch.setattr(daemon, "_confirm_command_acceptance", AsyncMock(return_value=True))

        # SC-3: Mock tmux_bridge to verify it's NOT called directly for polling by daemon_session
        # (It should be called by the agent_readiness module, which is mocked above)
        mock_bridge = AsyncMock()
        monkeypatch.setattr("teleclaude.daemon_session.tmux_bridge", mock_bridge)

        mock_db.get_session = AsyncMock(
            return_value=MagicMock(session_id=session_id, project_path="/tmp", subdir="", active_agent="claude")
        )

        # Call the method
        await daemon._handle_agent_then_message(session_id, ["claude", "slow", "hello"])

        # SC-2/SC-3: Verify readiness module was called
        mock_ready.assert_awaited_once()

        # SC-3: Verify daemon_session did NOT call tmux_bridge directly for capture (proving it used the result)
        # This tests the PUBLIC behavior/contract: use the module, don't poll directly.
        assert mock_bridge.capture_pane.call_count == 0, (
            "daemon_session should not call tmux_bridge.capture_pane directly"
        )

        # SC-4: Verify event was emitted with session_id
        found_ready = False
        for call in mock_emit.call_args_list:
            if call.args[0] == TeleClaudeEvents.AGENT_READY:
                ctx = call.args[1]
                assert ctx.session_id == session_id
                found_ready = True
                break
        assert found_ready, "AGENT_READY event not emitted"

    @pytest.mark.asyncio
    async def test_handle_agent_then_message_emits_timeout_event(self, monkeypatch):
        """Test that _handle_agent_then_message emits AGENT_READINESS_TIMEOUT on failure."""
        daemon = _TestDaemon()
        session_id = "sess-1"

        mock_db = AsyncMock()
        monkeypatch.setattr("teleclaude.daemon_session.db", mock_db)

        mock_ready = AsyncMock(return_value=(False, "still loading"))
        monkeypatch.setattr("teleclaude.daemon_session.wait_for_agent_ready", mock_ready, raising=False)

        mock_emit = MagicMock()
        monkeypatch.setattr("teleclaude.daemon_session.event_bus.emit", mock_emit)

        mock_terminate = AsyncMock()
        monkeypatch.setattr(
            "teleclaude.daemon_session.session_cleanup", SimpleNamespace(terminate_session=mock_terminate)
        )

        session_mock = MagicMock(session_id=session_id)
        mock_db.get_session = AsyncMock(return_value=session_mock)

        # Call the method
        await daemon._handle_agent_then_message(session_id, ["claude", "slow", "hello"])

        # SC-5: Verify event was emitted with session_id
        found_timeout = False
        for call in mock_emit.call_args_list:
            if call.args[0] == TeleClaudeEvents.AGENT_READINESS_TIMEOUT:
                ctx = call.args[1]
                assert ctx.session_id == session_id
                found_timeout = True
                break
        assert found_timeout, "AGENT_READINESS_TIMEOUT event not emitted"

        # SC-5: Verify session was closed/terminated
        mock_terminate.assert_awaited_once()

        # SC-5: Verify user was notified via client.send_message
        # Fix SC-5: Assert on structure/session, not human-facing prose
        daemon.client.send_message.assert_awaited_once()
        sent_session = daemon.client.send_message.call_args.args[0]
        assert sent_session.session_id == session_id
        # We don't assert on text content to avoid prose-lock
