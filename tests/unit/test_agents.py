import pytest

from teleclaude.config import AgentConfig
from teleclaude.core import agents


def _fake_config() -> dict[str, AgentConfig]:
    return {
        "claude": AgentConfig(
            command='claude --dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\'',
            session_dir="~/.claude/sessions",
            log_pattern="*.jsonl",
            model_flags={"fast": "-m haiku", "med": "-m sonnet", "slow": "-m opus"},
            exec_subcommand="",
            resume_template="{base_cmd} --resume {session_id}",
            continue_template="{base_cmd} --continue",
        ),
        "gemini": AgentConfig(
            command="gemini --yolo -i",
            session_dir="~/.gemini/sessions",
            log_pattern="*.jsonl",
            model_flags={
                "fast": "-m gemini-2.5-flash-lite",
                "med": "-m gemini-2.5-flash",
                "slow": "-m gemini-3-pro-preview",
            },
            exec_subcommand="",
            resume_template="{base_cmd} --resume {session_id}",
            continue_template="",
        ),
        "codex": AgentConfig(
            command="codex --dangerously-bypass-approvals-and-sandbox --search",
            session_dir="~/.codex/sessions",
            log_pattern="*.jsonl",
            model_flags={
                "fast": "-m gpt-5.1-codex-mini",
                "med": "-m gpt-5.1-codex",
                "slow": "-m gpt-5.2",
            },
            exec_subcommand="exec",
            resume_template="{base_cmd} resume {session_id}",
            continue_template="",
        ),
    }


@pytest.fixture(autouse=True)
def patch_config(monkeypatch):
    monkeypatch.setattr(agents, "config", type("Cfg", (), {"agents": _fake_config()})())
    yield


def test_get_agent_command_defaults_to_slow_mode():
    cmd = agents.get_agent_command("claude")
    assert "-m opus" in cmd


@pytest.mark.parametrize(
    "agent,mode,expected_flag",
    [
        ("claude", "fast", "-m haiku"),
        ("claude", "med", "-m sonnet"),
        ("gemini", "fast", "-m gemini-2.5-flash-lite"),
        ("gemini", "slow", "-m gemini-3-pro-preview"),
        ("codex", "med", "-m gpt-5.1-codex"),
    ],
)
def test_get_agent_command_applies_model_flags(agent, mode, expected_flag):
    cmd = agents.get_agent_command(agent, thinking_mode=mode)
    assert expected_flag in cmd


def test_get_agent_command_exec_subcommand_for_codex():
    cmd = agents.get_agent_command("codex", thinking_mode="slow", exec=True)
    assert "exec" in cmd.split()
    assert cmd.index("exec") > cmd.index("codex")


def test_get_agent_command_resume_flag_when_requested():
    cmd = agents.get_agent_command("claude", resume=True)
    assert cmd.endswith("--continue")
    assert "-m opus" not in cmd  # continue_template path skips model flag


def test_get_agent_command_native_session_id_uses_template():
    cmd = agents.get_agent_command("gemini", native_session_id="abc123")
    assert "--resume abc123" in cmd
    assert "-m gemini" not in cmd  # resume_template path skips model flag


def test_get_agent_command_invalid_mode_raises():
    with pytest.raises(ValueError):
        agents.get_agent_command("claude", thinking_mode="ultra")
