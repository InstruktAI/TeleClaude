"""Agent session environment assembly."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from teleclaude.config.loader import load_global_config, load_project_config
from teleclaude.runtime.environment import filter_platform_session_environment
from teleclaude.utils import resolve_project_config_path


def _load_agent_env_allow_list(project_path: str | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for name in load_global_config().env_allow_list:
        if name in seen:
            continue
        seen.add(name)
        result.append(name)

    if not project_path:
        return result

    config_path = resolve_project_config_path(Path(project_path))
    if not config_path.exists():
        return result

    for name in load_project_config(config_path).env_allow_list:
        if name in seen:
            continue
        seen.add(name)
        result.append(name)

    return result


def build_agent_session_environment(
    *,
    project_path: str | None,
    platform_env: Mapping[str, str] | None = None,
    source_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return env vars explicitly allowed for an agent tmux session."""

    source = source_env if source_env is not None else os.environ
    env_vars: dict[str, str] = {}
    for name in _load_agent_env_allow_list(project_path):
        if name in source:
            env_vars[name] = source[name]

    env_vars.update(filter_platform_session_environment(source))
    env_vars.update(filter_platform_session_environment(platform_env or {}))
    return env_vars
