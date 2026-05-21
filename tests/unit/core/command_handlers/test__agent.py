"""Characterization tests for teleclaude.core.command_handlers._agent."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.constants import HUMAN_ROLE_ADMIN
from teleclaude.core.agent_readiness import WINNER_HOOK, WINNER_PANE, ReadinessRaceResult
from teleclaude.core.agents import AgentName
from teleclaude.core.command_handlers import _agent
from teleclaude.core.command_handlers import _utils as command_utils
from teleclaude.core.events import TeleClaudeEvents
from teleclaude.core.models import Session
from teleclaude.types.commands import RestartAgentCommand, ResumeAgentCommand, RunAgentCommand, StartAgentCommand


def make_session(
    *,
    session_id: str = "sess-001",
    tmux_session_name: str = "tc-sess-001",
    lifecycle_status: str = "active",
    human_role: str | None = HUMAN_ROLE_ADMIN,
    active_agent: str | None = None,
    thinking_mode: str | None = "slow",
    native_session_id: str | None = None,
) -> Session:
    """Build a concrete session for agent handler tests."""
    return Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name=tmux_session_name,
        title="Session",
        lifecycle_status=lifecycle_status,
        human_role=human_role,
        active_agent=active_agent,
        thinking_mode=thinking_mode,
        native_session_id=native_session_id,
    )


def patch_handler_db(monkeypatch: pytest.MonkeyPatch, db: SimpleNamespace) -> None:
    """Patch both the handler module and shared decorator to use a fake DB."""
    monkeypatch.setattr(_agent, "db", db)
    monkeypatch.setattr(command_utils, "db", db)


class TestGetSessionProfile:
    @pytest.mark.unit
    def test_admin_sessions_use_default_profile(self) -> None:
        assert _agent._get_session_profile(make_session(human_role=HUMAN_ROLE_ADMIN)) == "default"

    @pytest.mark.unit
    def test_non_admin_sessions_use_restricted_profile(self) -> None:
        assert _agent._get_session_profile(make_session(human_role="member")) == "restricted"


class TestStartAgent:
    @pytest.mark.unit
    async def test_deep_mode_is_rejected_for_non_codex_agents(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session()
        db = SimpleNamespace(get_session=AsyncMock(return_value=session), update_session=AsyncMock())
        client = SimpleNamespace(send_message=AsyncMock())
        execute_terminal_command = AsyncMock(return_value=True)

        patch_handler_db(monkeypatch, db)
        monkeypatch.setattr(_agent, "assert_agent_enabled", lambda agent_name: agent_name)

        cmd = StartAgentCommand(session_id=session.session_id, agent_name="claude", args=["deep", "scan repo"])

        await _agent.start_agent.__wrapped__(session, cmd, client, execute_terminal_command)

        client.send_message.assert_awaited_once()
        db.update_session.assert_not_awaited()
        execute_terminal_command.assert_not_awaited()

    @pytest.mark.unit
    async def test_start_agent_uses_leading_mode_flag_and_quotes_prompt(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = make_session(thinking_mode="slow")
        db = SimpleNamespace(get_session=AsyncMock(return_value=session), update_session=AsyncMock())
        client = SimpleNamespace(send_message=AsyncMock())
        execute_terminal_command = AsyncMock(return_value=True)
        get_agent_command = MagicMock(return_value="codex-cli")

        patch_handler_db(monkeypatch, db)
        monkeypatch.setattr(_agent, "assert_agent_enabled", lambda agent_name: agent_name)
        monkeypatch.setattr(_agent, "get_agent_command", get_agent_command)

        cmd = StartAgentCommand(
            session_id=session.session_id,
            agent_name="codex",
            args=["fast", "hello world", "--json"],
        )

        await _agent.start_agent.__wrapped__(session, cmd, client, execute_terminal_command)

        get_agent_command.assert_called_once_with(
            "codex",
            thinking_mode="fast",
            interactive=True,
            profile="default",
        )
        db.update_session.assert_any_await(session.session_id, thinking_mode="fast")
        final_update = db.update_session.await_args_list[-1]
        assert final_update.args == (session.session_id,)
        assert final_update.kwargs["active_agent"] == "codex"
        assert final_update.kwargs["thinking_mode"] == "fast"
        assert final_update.kwargs["last_message_sent"] == "hello world --json"
        execute_terminal_command.assert_awaited_once_with(
            session.session_id,
            "codex-cli 'hello world' --json",
            None,
            True,
        )

    @pytest.mark.unit
    async def test_start_agent_records_last_input_origin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Acceptance boundary: start_agent writes last_input_origin from cmd.origin."""
        session = make_session()
        db = SimpleNamespace(get_session=AsyncMock(return_value=session), update_session=AsyncMock())
        client = SimpleNamespace(send_message=AsyncMock())
        execute_terminal_command = AsyncMock(return_value=True)

        patch_handler_db(monkeypatch, db)
        monkeypatch.setattr(_agent, "assert_agent_enabled", lambda agent_name: agent_name)
        monkeypatch.setattr(_agent, "get_agent_command", MagicMock(return_value="claude-cli"))

        cmd = StartAgentCommand(session_id=session.session_id, agent_name="claude", origin="telegram")

        await _agent.start_agent.__wrapped__(session, cmd, client, execute_terminal_command)

        final_update = db.update_session.await_args_list[-1]
        assert final_update.kwargs["last_input_origin"] == "telegram"


class TestResumeAgent:
    @pytest.mark.unit
    async def test_resume_agent_uses_session_agent_and_override_native_session(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = make_session(active_agent="codex", thinking_mode="fast", native_session_id="native-1")
        db = SimpleNamespace(get_session=AsyncMock(return_value=session), update_session=AsyncMock())
        client = SimpleNamespace(send_message=AsyncMock())
        execute_terminal_command = AsyncMock(return_value=True)
        get_agent_command = MagicMock(return_value="codex resume")

        patch_handler_db(monkeypatch, db)
        monkeypatch.setattr(_agent, "assert_agent_enabled", lambda agent_name: agent_name)
        monkeypatch.setattr(_agent, "get_agent_command", get_agent_command)

        cmd = ResumeAgentCommand(session_id=session.session_id, native_session_id="native-2")

        await _agent.resume_agent.__wrapped__(session, cmd, client, execute_terminal_command)

        db.update_session.assert_any_await(session.session_id, native_session_id="native-2")
        db.update_session.assert_any_await(session.session_id, active_agent="codex")
        get_agent_command.assert_called_once_with(
            agent="codex",
            thinking_mode="fast",
            exec=False,
            resume=False,
            native_session_id="native-2",
            profile="default",
        )
        execute_terminal_command.assert_awaited_once_with(session.session_id, "codex resume", None, True)

    @pytest.mark.unit
    async def test_resume_agent_records_last_input_origin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Acceptance boundary: resume_agent writes last_input_origin from cmd.origin."""
        session = make_session(active_agent="claude", thinking_mode="slow")
        db = SimpleNamespace(get_session=AsyncMock(return_value=session), update_session=AsyncMock())
        client = SimpleNamespace(send_message=AsyncMock())
        execute_terminal_command = AsyncMock(return_value=True)

        patch_handler_db(monkeypatch, db)
        monkeypatch.setattr(_agent, "assert_agent_enabled", lambda agent_name: agent_name)
        monkeypatch.setattr(_agent, "get_agent_command", MagicMock(return_value="claude --resume"))

        cmd = ResumeAgentCommand(session_id=session.session_id, origin="discord")

        await _agent.resume_agent.__wrapped__(session, cmd, client, execute_terminal_command)

        final_update = db.update_session.await_args_list[-1]
        assert final_update.kwargs["last_input_origin"] == "discord"


class TestAgentRestart:
    @pytest.mark.unit
    async def test_restart_requires_native_session_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session(active_agent="codex", native_session_id=None)
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        event_bus = SimpleNamespace(emit=MagicMock())
        client = SimpleNamespace(send_message=AsyncMock())
        execute_terminal_command = AsyncMock(return_value=True)

        patch_handler_db(monkeypatch, db)
        monkeypatch.setattr(_agent, "event_bus", event_bus)

        ok, error = await _agent.agent_restart.__wrapped__(
            session,
            RestartAgentCommand(session_id=session.session_id),
            client,
            execute_terminal_command,
        )

        assert ok is False
        assert error is not None
        event_bus.emit.assert_called_once()
        assert event_bus.emit.call_args.args[0] == TeleClaudeEvents.ERROR
        client.send_message.assert_awaited_once()
        execute_terminal_command.assert_not_awaited()


class TestRunAgentCommand:
    @pytest.mark.unit
    async def test_run_agent_command_records_and_executes_slash_command(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = make_session(active_agent="codex")
        db = SimpleNamespace(get_session=AsyncMock(return_value=session), update_session=AsyncMock())
        client = SimpleNamespace(send_message=AsyncMock())
        execute_terminal_command = AsyncMock(return_value=True)

        patch_handler_db(monkeypatch, db)
        monkeypatch.setattr(_agent, "assert_agent_enabled", lambda agent_name: agent_name)

        cmd = RunAgentCommand(
            session_id=session.session_id,
            command="status",
            args="--json",
            origin="discord",
        )

        await _agent.run_agent_command.__wrapped__(session, cmd, client, execute_terminal_command)

        update_call = db.update_session.await_args
        assert update_call.args == (session.session_id,)
        assert update_call.kwargs["last_message_sent"] == "/status --json"
        assert update_call.kwargs["last_input_origin"] == "discord"
        execute_terminal_command.assert_awaited_once_with(session.session_id, "/status --json", None, True)


class TestAwaitRestartReadiness:
    """Verify the restart-path wrapper delegates to race_for_readiness and
    emits structured readiness_winner logs."""

    @pytest.mark.unit
    async def test_wrapper_delegates_to_race_with_agent_name_passthrough(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The wrapper must NOT branch on agent — it must forward the agent
        # name to race_for_readiness as-is. Codex's prior special-case branch
        # is gone; every adapter follows the same delegation. The peer-
        # observable contract is the kwargs handed to race_for_readiness.
        session = make_session(active_agent=AgentName.GEMINI.value)
        loop = asyncio.get_event_loop()
        ready_future: asyncio.Future[None] = loop.create_future()
        ready_future.set_result(None)

        race_mock = AsyncMock(return_value=ReadinessRaceResult(winner=WINNER_HOOK, elapsed_s=0.001))
        monkeypatch.setattr(_agent, "race_for_readiness", race_mock)
        monkeypatch.setattr(_agent.logger, "info", MagicMock())

        await _agent._await_restart_readiness(
            agent=AgentName.GEMINI.value,
            session=session,
            ready_future=ready_future,
        )

        race_mock.assert_awaited_once()
        call_kwargs = race_mock.await_args.kwargs
        assert call_kwargs["agent_name"] == AgentName.GEMINI.value
        assert call_kwargs["session"] is session
        assert call_kwargs["ready_future"] is ready_future
        assert call_kwargs["pane_task_name"]
        assert call_kwargs["hook_task_name"]

    @pytest.mark.unit
    async def test_hook_win_emits_structured_winner_log(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = make_session(active_agent=AgentName.CLAUDE.value)
        loop = asyncio.get_event_loop()
        ready_future: asyncio.Future[None] = loop.create_future()
        ready_future.set_result(None)

        race_mock = AsyncMock(return_value=ReadinessRaceResult(winner=WINNER_HOOK, elapsed_s=0.012))
        monkeypatch.setattr(_agent, "race_for_readiness", race_mock)
        info_mock = MagicMock()
        monkeypatch.setattr(_agent.logger, "info", info_mock)

        await _agent._await_restart_readiness(
            agent=AgentName.CLAUDE.value,
            session=session,
            ready_future=ready_future,
        )

        info_mock.assert_called_once()
        assert info_mock.call_args.args[0]
        log_kwargs = info_mock.call_args.kwargs
        assert log_kwargs["winner"] == WINNER_HOOK
        assert log_kwargs["adapter"] == AgentName.CLAUDE.value
        assert log_kwargs["session_id"] == session.session_id
        assert log_kwargs["phase"]
        assert log_kwargs["hook_lag_ms"] == 12

    @pytest.mark.unit
    async def test_pane_win_emits_structured_winner_log(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = make_session(active_agent=AgentName.CLAUDE.value)
        loop = asyncio.get_event_loop()
        ready_future: asyncio.Future[None] = loop.create_future()

        race_mock = AsyncMock(
            return_value=ReadinessRaceResult(winner=WINNER_PANE, elapsed_s=1.234, tail="snapshot"),
        )
        monkeypatch.setattr(_agent, "race_for_readiness", race_mock)
        info_mock = MagicMock()
        monkeypatch.setattr(_agent.logger, "info", info_mock)

        await _agent._await_restart_readiness(
            agent=AgentName.CLAUDE.value,
            session=session,
            ready_future=ready_future,
        )

        log_kwargs = info_mock.call_args.kwargs
        assert log_kwargs["winner"] == WINNER_PANE
        assert log_kwargs["phase"]
        assert log_kwargs["elapsed_ms"] == 1234
