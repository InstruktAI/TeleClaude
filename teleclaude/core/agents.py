"""Shared Agent metadata."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from teleclaude.config import AgentConfig, config


class AgentName(str, Enum):
    """Known AI agent names."""

    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"

    @classmethod
    def from_str(cls, value: str) -> "AgentName":
        """Convert a string to AgentName, raising ValueError on unknown values."""
        normalized = value.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(f"Unknown agent '{value}'")


def _get_agent_config(agent: str) -> AgentConfig:
    """Fetch AgentConfig or raise clear error for unknown agent."""
    cfg = config.agents.get(agent)
    if not cfg:
        raise ValueError(f"Unknown agent '{agent}'")
    return cfg


def get_agent_command(
    agent: str,
    thinking_mode: str = "slow",
    exec: bool = False,  # noqa: A003 - follows public API naming
    resume: bool = False,
    native_session_id: Optional[str] = None,
) -> str:
    """
    Build agent command string.

    Consolidates all agent command assembly into a single function.
    Handles both fresh starts and session resumption.

    Args:
        agent: Agent name ('claude', 'gemini', 'codex')
        thinking_mode: Model tier ('fast', 'med', 'slow'). Default 'slow' (most capable).
        exec: If True, include exec_subcommand after base command (e.g., 'exec' for Codex)
        resume: If True and no native_session_id, uses continue_template when available (agent-specific "continue latest")
        native_session_id: If provided, uses resume_template with this session ID (ignores resume flag)

    Returns:
        Assembled command string, ready for prompt to be appended.

    Command assembly order:
        - With native_session_id: resume_template.format(base_cmd=..., session_id=...)
        - Without: {base_command} {exec_subcommand?} {model_flags} {--resume?}

    Examples:
        >>> get_agent_command("claude", thinking_mode="fast")
        'claude --dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\' -m haiku'

        >>> get_agent_command("codex", thinking_mode="slow", exec=True)
        'codex exec --dangerously-bypass-approvals-and-sandbox --search -m gpt-5.2'

        >>> get_agent_command("claude", native_session_id="abc123")
        'claude --dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\' --resume abc123'
    """
    agent_cfg = _get_agent_config(agent)
    base_cmd = agent_cfg.command.strip()

    if native_session_id:
        return agent_cfg.resume_template.format(base_cmd=base_cmd, session_id=native_session_id)

    if resume and agent_cfg.continue_template:
        # Agent-specific continue semantics (e.g., `claude --continue`, `codex resume --latest`).
        # Intentionally skips model flags to avoid overriding an existing conversation's settings.
        return agent_cfg.continue_template.format(base_cmd=base_cmd)

    model_flag = agent_cfg.model_flags.get(thinking_mode)
    if model_flag is None:
        raise ValueError(f"Invalid thinking_mode '{thinking_mode}' for agent '{agent}'")

    parts: list[str] = [base_cmd]

    if exec and agent_cfg.exec_subcommand:
        parts.append(agent_cfg.exec_subcommand)

    if model_flag:
        parts.append(model_flag)

    if resume:
        parts.append("--resume")

    return " ".join(parts)
