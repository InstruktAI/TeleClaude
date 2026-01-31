"""Role-based tool filtering for TeleClaude MCP.

This module defines which tools are available to different agent roles.
Filtering only applies when a role marker is present and role == worker.
"""

from typing import TypedDict

from teleclaude.constants import ROLE_WORKER

# Worker tool access policy.
WORKER_EXCLUDED_TOOLS = {
    "teleclaude__next_work",
    "teleclaude__next_prepare",
    "teleclaude__mark_phase",
    "teleclaude__start_session",
    "teleclaude__send_message",
    "teleclaude__run_agent_command",
}


class ToolSpec(TypedDict, total=False):
    """Minimal tool spec used for filtering."""

    name: str


def get_excluded_tools(role: str | None) -> set[str]:
    """Return set of tool names excluded for this role."""
    if role == ROLE_WORKER:
        return WORKER_EXCLUDED_TOOLS
    return set()


def is_tool_allowed(role: str | None, tool_name: str) -> bool:
    """Return whether a tool is allowed for the given role.

    Args:
        role: The role name, if any.
        tool_name: The tool name.

    Returns:
        True if the tool is allowed for the role or no filtering applies.
    """
    return tool_name not in get_excluded_tools(role)


def filter_tool_names(role: str | None, tool_names: list[str]) -> list[str]:
    """Return filtered tool names for a role.

    If no role marker is found, returns the original list (no filtering).
    """
    excluded = get_excluded_tools(role)
    if not excluded:
        return tool_names
    return [name for name in tool_names if name not in excluded]


def filter_tool_specs(role: str | None, tools: list[ToolSpec]) -> list[ToolSpec]:
    """Return filtered tool specs for a role.

    If no role marker is found, returns the original list (no filtering).
    """
    excluded = get_excluded_tools(role)
    if not excluded:
        return tools
    return [tool for tool in tools if tool.get("name") not in excluded]


def get_allowed_tools(role: str | None, all_tool_names: list[str]) -> list[str]:
    """Return list of allowed tool names for a role.

    Args:
        role: The role name, if any.
        all_tool_names: Full list of available tool names.

    Returns:
        Filtered list of tool names.
    """
    return filter_tool_names(role, all_tool_names)
