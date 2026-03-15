"""Characterization tests for teleclaude.core.command_handlers._agent."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.constants import HUMAN_ROLE_ADMIN
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

        await _agent.start_agent(cmd, client, execute_terminal_command)

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

        await _agent.start_agent(cmd, client, execute_terminal_command)

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

        await _agent.resume_agent(cmd, client, execute_terminal_command)

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

        ok, error = await _agent.agent_restart(
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

        await _agent.run_agent_command(cmd, client, execute_terminal_command)

        update_call = db.update_session.await_args
        assert update_call.args == (session.session_id,)
        assert update_call.kwargs["last_message_sent"] == "/status --json"
        assert update_call.kwargs["last_input_origin"] == "discord"
        execute_terminal_command.assert_awaited_once_with(session.session_id, "/status --json", None, True)
