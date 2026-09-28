"""Certain edit-tool path extraction from native hook inputs."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from teleclaude.core.agents import AgentName

from ._extractors._common import (
    _APPLY_PATCH_TOOL,
    _PATCH_FIELDS,
    CERTAIN_EDIT_TOOLS,
    _canonical_tool_name,
    _extract_apply_patch_paths,
    _extract_path_values,
)

__all__ = ["certain_edit_paths"]


def certain_edit_paths(
    agent: AgentName,
    tool_name: str,
    tool_input: Mapping[str, object],
    *,
    workspace_root: Path,
) -> tuple[str, ...]:
    """Return workspace-relative paths explicitly named by a certain edit tool."""
    canonical_name = _canonical_tool_name(tool_name)
    if canonical_name not in CERTAIN_EDIT_TOOLS[agent]:
        return ()

    workspace = str(workspace_root)
    paths = _extract_path_values(tool_input, workspace)
    if canonical_name == _APPLY_PATCH_TOOL:
        for key in _PATCH_FIELDS:
            value = tool_input.get(key)
            if isinstance(value, str):
                paths.update(_extract_apply_patch_paths(value, workspace))
    return tuple(sorted(paths))
