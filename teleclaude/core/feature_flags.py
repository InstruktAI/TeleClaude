"""Feature-flag helpers used at routing junctions."""

from teleclaude.config import config
from teleclaude.core.agents import AgentName

THREADED_OUTPUT_EXPERIMENT = "ui_threaded_agent_stop_output"
THREADED_OUTPUT_INCLUDE_TOOLS_EXPERIMENT = "ui_threaded_agent_stop_output_include_tools"


def _normalize_agent(agent_key: str | None) -> str | None:
    """Normalize agent key or return None when missing."""
    if not agent_key:
        return None
    normalized = agent_key.strip().lower()
    return normalized or None


def is_threaded_output_enabled(agent_key: str | None) -> bool:
    """Return True only when threaded-output experiment is enabled for Gemini."""
    normalized_agent = _normalize_agent(agent_key)
    if normalized_agent != AgentName.GEMINI.value:
        return False
    return config.is_experiment_enabled(THREADED_OUTPUT_EXPERIMENT, normalized_agent)


def is_threaded_output_include_tools_enabled(agent_key: str | None) -> bool:
    """Return True when threaded output is enabled and tool blocks are included."""
    normalized_agent = _normalize_agent(agent_key)
    if normalized_agent is None:
        return False
    if not is_threaded_output_enabled(normalized_agent):
        return False
    return config.is_experiment_enabled(THREADED_OUTPUT_INCLUDE_TOOLS_EXPERIMENT, normalized_agent)
