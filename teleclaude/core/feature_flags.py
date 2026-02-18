"""Feature-flag helpers used at routing junctions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.config import config
from teleclaude.core.models import AdapterType

if TYPE_CHECKING:
    from teleclaude.core.models import Session

THREADED_OUTPUT_EXPERIMENT = "ui_threaded_agent_stop_output"
THREADED_OUTPUT_INCLUDE_TOOLS_EXPERIMENT = "ui_threaded_agent_stop_output_include_tools"
DISCORD_PROJECT_FORUM_MIRRORING = "discord_project_forum_mirroring"


def _normalize_agent(agent_key: str | None) -> str | None:
    """Normalize agent key or return None when missing."""
    if not agent_key:
        return None
    normalized = agent_key.strip().lower()
    return normalized or None


def is_threaded_output_enabled(agent_key: str | None) -> bool:
    """Return True when threaded-output experiment is enabled for the given agent.

    The experiment config's agents list gates which agents get threaded output.
    If the agents list is empty/None, the experiment applies to all agents.
    """
    normalized_agent = _normalize_agent(agent_key)
    return config.is_experiment_enabled(THREADED_OUTPUT_EXPERIMENT, normalized_agent)


def is_threaded_output_enabled_for_session(session: "Session") -> bool:
    """Return True when threaded output is enabled for a session.

    Threaded output is on when:
    - The experiment flag is enabled for the session's active agent, OR
    - The session's origin adapter is Discord (all Discord sessions use threaded output)
    """
    if session.last_input_origin == AdapterType.DISCORD.value:
        return True
    return is_threaded_output_enabled(session.active_agent)


def is_discord_project_forum_mirroring_enabled() -> bool:
    """Return True when project-scoped Discord forum mirroring is enabled."""
    return config.is_experiment_enabled(DISCORD_PROJECT_FORUM_MIRRORING)


def is_threaded_output_include_tools_enabled(agent_key: str | None) -> bool:
    """Return True when threaded output is enabled and tool blocks are included."""
    normalized_agent = _normalize_agent(agent_key)
    if normalized_agent is None:
        return False
    if not is_threaded_output_enabled(normalized_agent):
        return False
    return config.is_experiment_enabled(THREADED_OUTPUT_INCLUDE_TOOLS_EXPERIMENT, normalized_agent)
