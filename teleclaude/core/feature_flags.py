"""Feature-flag helpers used at routing junctions."""

from __future__ import annotations

from teleclaude.config import config

THREADED_OUTPUT_EXPERIMENT = "threaded_output"
DISCORD_PROJECT_FORUM_MIRRORING = "discord_project_forum_mirroring"


def _normalize_agent(agent_key: str | None) -> str | None:
    """Normalize agent key or return None when missing."""
    if not agent_key:
        return None
    normalized = agent_key.strip().lower()
    return normalized or None


def is_threaded_output_enabled(agent_key: str | None, adapter: str | None = None) -> bool:
    """Return True when threaded-output experiment is enabled.

    When adapter is provided, checks the specific agent+adapter combination.
    When adapter is omitted, optimistically matches any adapter-constrained entry
    (useful for the coordinator asking "does any adapter want this?").
    """
    normalized_agent = _normalize_agent(agent_key)
    return config.is_experiment_enabled(THREADED_OUTPUT_EXPERIMENT, normalized_agent, adapter=adapter)


def is_discord_project_forum_mirroring_enabled() -> bool:
    """Return True when project-scoped Discord forum mirroring is enabled."""
    return config.is_experiment_enabled(DISCORD_PROJECT_FORUM_MIRRORING)
