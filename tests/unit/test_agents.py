import os

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

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
            interactive_flag="-p",
            non_interactive_flag="-p",
            resume_template="{base_cmd} --resume {session_id}",
            continue_template="{base_cmd} --continue",
        ),
        "gemini": AgentConfig(
            command="gemini --yolo",
            session_dir="~/.gemini/sessions",
            log_pattern="*.jsonl",
            model_flags={
                "fast": "-m gemini-2.5-flash-lite",
                "med": "-m gemini-2.5-flash",
                "slow": "-m gemini-3-pro-preview",
            },
            exec_subcommand="",
            interactive_flag="-i",
            non_interactive_flag="",
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
            interactive_flag="",
            non_interactive_flag="",
            resume_template="{base_cmd} resume {session_id}",
            continue_template="",
        ),
    }


@pytest.fixture(autouse=True)
def patch_config(monkeypatch):
    monkeypatch.setattr(agents, "config", type("Cfg", (), {"agents": _fake_config()})())
    yield


def test_get_agent_command_defaults_to_slow_mode():
    """Test that get_agent_command defaults to the slow model flag."""
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
    """Test that get_agent_command uses the model flag matching requested mode."""
    cmd = agents.get_agent_command(agent, thinking_mode=mode)
    assert expected_flag in cmd


def test_get_agent_command_exec_subcommand_for_codex():
    """Test that exec subcommand is inserted for codex when exec is True."""
    cmd = agents.get_agent_command("codex", thinking_mode="slow", exec=True)
    assert "exec" in cmd.split()
    assert cmd.index("exec") > cmd.index("codex")


def test_get_agent_command_resume_flag_when_requested():
    """Test that resume uses continue template and skips model flags."""
    cmd = agents.get_agent_command("claude", resume=True)
    assert cmd.endswith("--continue")
    assert "-m opus" not in cmd  # continue_template path skips model flag


def test_get_agent_command_native_session_id_uses_template():
    """Test that native session id uses resume template and includes model flag."""
    cmd = agents.get_agent_command("gemini", native_session_id="abc123", thinking_mode="slow")
    assert "--resume abc123" in cmd
    assert "-m gemini-3-pro-preview" in cmd  # model flag included for explicit session resume


def test_get_agent_command_native_session_id_omits_model_when_none():
    """Test that native session id omits model flag when thinking_mode=None."""
    cmd = agents.get_agent_command("gemini", native_session_id="abc123", thinking_mode=None)
    assert "--resume abc123" in cmd
    assert " -m " not in cmd


def test_get_agent_command_invalid_mode_raises():
    """Test that unknown thinking_mode raises a ValueError."""
    with pytest.raises(ValueError):
        agents.get_agent_command("claude", thinking_mode="ultra")


def test_get_agent_command_interactive_flag_appended_at_end():
    """Interactive flag should be appended at the end of the command."""
    cmd = agents.get_agent_command("gemini", thinking_mode="fast", interactive=True)
    # Flag should be at the end
    assert cmd.endswith("-i")
    # Model flag should come before interactive flag
    assert cmd.index("-m gemini-2.5-flash-lite") < cmd.index("-i")


def test_get_agent_command_no_interactive_flag_when_not_requested():
    """Interactive flag should not be added when interactive=False."""
    cmd = agents.get_agent_command("gemini", thinking_mode="fast", interactive=False)
    # Command should not end with -i (unless it's part of the model name)
    assert not cmd.endswith(" -i")


def test_get_agent_command_interactive_flag_skipped_when_empty():
    """Agents without interactive_flag should not append anything."""
    cmd = agents.get_agent_command("codex", thinking_mode="fast", interactive=True)
    # Codex has empty interactive_flag, so command should just have model flag at end
    assert cmd.endswith("-m gpt-5.1-codex-mini")
