"""Shared Agent metadata.

``AgentName`` and every fixed per-agent fact (prompt markers, startup signal,
Discord presentation, git identity, launch protocol) are canonically owned
by ``teleclaude.agent_registry``, a leaf module with no internal
dependencies. This module re-exports that vocabulary and adds the
config-dependent accessors a leaf registry module cannot own itself.
"""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.agent_registry import AGENT_REGISTRY as AGENT_REGISTRY
from teleclaude.agent_registry import AgentName as AgentName
from teleclaude.agent_registry import AgentStartupSignal as AgentStartupSignal
from teleclaude.agent_registry import DiscordAuthorPresentation as DiscordAuthorPresentation
from teleclaude.config import AgentConfig, config

logger = get_logger(__name__)

KNOWN_AGENT_IDS: tuple[str, ...] = AgentName.choices()


def resolve_parser_agent(active_agent: str | None) -> AgentName:
    """Resolve a raw active_agent string to AgentName with fallback to Claude.

    Logs at debug level for None/empty (expected on fresh sessions) and at
    warning level for genuinely unknown values.
    """
    if not active_agent:
        logger.debug("active_agent is None or empty; defaulting parser to Claude")
        return AgentName.CLAUDE
    try:
        return AgentName.from_str(active_agent)
    except ValueError:
        logger.warning(
            "Unknown active_agent %r; defaulting parser to Claude",
            active_agent,
        )
        return AgentName.CLAUDE


def normalize_agent_name(value: str) -> str:
    """Normalize and validate an agent name, returning the canonical value."""
    return AgentName.from_str(value).value


def get_known_agents() -> tuple[str, ...]:
    """Return canonical known agent IDs in stable order."""
    return KNOWN_AGENT_IDS


def get_enabled_agents() -> tuple[str, ...]:
    """Return known agents currently enabled by config policy."""
    return tuple(agent.value for agent in AgentName if config.agents[agent].enabled)


def is_agent_enabled(name: str) -> bool:
    """Return True when the provided agent name is known and enabled."""
    try:
        normalized = normalize_agent_name(name)
    except ValueError:
        return False
    cfg = config.agents.get(AgentName.from_str(normalized))
    return bool(cfg and cfg.enabled)


def assert_agent_enabled(name: str) -> str:
    """Validate selection against config-enabled policy and return normalized name."""
    normalized = normalize_agent_name(name)
    agent_name = AgentName.from_str(normalized)
    cfg = config.agents.get(agent_name)
    if cfg is None:
        allowed = ", ".join(get_known_agents())
        raise ValueError(f"Unknown agent '{name}'. Allowed agents: {allowed}.")
    if not cfg.enabled:
        enabled = ", ".join(get_enabled_agents()) or "none"
        raise ValueError(
            f"Agent '{normalized}' is disabled by `config.yml:agents.{normalized}.enabled`. "
            f"Enable it in config.yml or choose an enabled agent ({enabled})."
        )
    return normalized


def get_default_agent() -> str:
    """Return the config-declared default agent name."""
    return assert_agent_enabled(config.default_agent.value)


def is_agent_title(title: str) -> bool:
    """Return True if a tmux pane title appears to belong to any known agent."""
    lowered = title.lower()
    return any(agent.value in lowered for agent in AgentName)


def _get_agent_config(agent: str) -> AgentConfig:
    """Fetch AgentConfig or raise clear error for unknown agent."""
    cfg = config.agents.get(AgentName.from_str(agent))
    if not cfg:
        raise ValueError(f"Unknown agent '{agent}'")
    return cfg


def render_mode_flags(agent: str, mode: str, model: str | None = None) -> str:
    """Return the opaque launch flags of one declared model-chain entry, verbatim."""
    agent_cfg = _get_agent_config(agent)
    entries = agent_cfg.mode_chains.get(mode)
    if entries is None:
        raise ValueError(f"Invalid thinking_mode '{mode}' for agent '{agent}'")
    if not entries:
        return ""
    if model is None:
        return entries[0].flags
    for chain in (agent_cfg.model_chains.get(mode, []), entries):
        for entry in chain:
            if entry.model == model:
                return entry.flags
    raise ValueError(f"Invalid model '{model}' for agent '{agent}' mode '{mode}'")


def get_agent_command(
    agent: str,
    thinking_mode: str | None = "slow",
    exec: bool = False,
    resume: bool = False,
    native_session_id: str | None = None,
    interactive: bool = False,
    profile: str = "default",
    resolved_flags: str | None = None,
) -> str:
    """
    Build agent command string.

    Consolidates all agent command assembly into a single function.
    Handles both fresh starts and session resumption.

    Args:
        agent: Agent name ('claude', 'gemini', 'codex')
        thinking_mode: Model tier ('fast', 'med', 'slow'). Default 'slow' (most capable).
            If None, omit model flags entirely.
        exec: If True, include exec_subcommand after base command (e.g., 'exec' for Codex)
        resume: If True and no native_session_id, uses continue_template when available (agent-specific "continue latest")
        native_session_id: If provided, uses resume_template with this session ID (ignores resume flag)
        interactive: If True, include interactive_flag at the end (right before prompt)
        profile: Security profile ('default', 'restricted'). Default 'default'.

    Returns:
        Assembled command string, ready for prompt to be appended.

    Command assembly order:
        - With native_session_id: resume_template.format(base_cmd=<base + model_flag>, session_id=...)
        - Without: {base_command} {exec_subcommand?} {model_flags} {--resume?} {interactive_flag?}

    Examples:
        >>> get_agent_command("claude", thinking_mode="fast")
        'claude --dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\' -m haiku'

        >>> get_agent_command("codex", thinking_mode="slow", exec=True)
        'codex exec --dangerously-bypass-approvals-and-sandbox --search -m gpt-5.5'

        >>> get_agent_command("claude", native_session_id="abc123")
        'claude --dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\' --resume abc123'
    """
    agent_cfg = _get_agent_config(agent)
    base_cmd = agent_cfg.get_command(profile).strip()

    if native_session_id:
        # Include model flag when resuming with explicit session ID (unless omitted)
        if thinking_mode is None:
            base_with_model = base_cmd
        else:
            resume_model_flag = (
                resolved_flags if resolved_flags is not None else render_mode_flags(agent, thinking_mode)
            )
            base_with_model = f"{base_cmd} {resume_model_flag}" if resume_model_flag else base_cmd
        return agent_cfg.resume_template.format(base_cmd=base_with_model, session_id=native_session_id)

    if resume and agent_cfg.continue_template:
        # Agent-specific continue semantics (e.g., `claude --continue`, `codex resume --latest`).
        # Intentionally skips model flags to avoid overriding an existing conversation's settings.
        return agent_cfg.continue_template.format(base_cmd=base_cmd)

    if thinking_mode is None:
        model_flag = ""
    else:
        model_flag = resolved_flags if resolved_flags is not None else render_mode_flags(agent, thinking_mode)

    parts: list[str] = [base_cmd]

    if exec and agent_cfg.exec_subcommand:
        parts.append(agent_cfg.exec_subcommand)

    if model_flag:
        parts.append(model_flag)

    if resume:
        parts.append("--resume")

    # Add interactive flag at the end (right before prompt will be appended)
    if interactive and agent_cfg.interactive_flag:
        parts.append(agent_cfg.interactive_flag)

    return " ".join(parts)
