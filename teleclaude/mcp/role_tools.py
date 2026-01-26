"""Role-based tool filtering for TeleClaude MCP.

This module defines which tools are available to different agent roles.
"""

from typing import TypedDict

# Non-orchestrators can access only a minimal tool set.
NON_ORCHESTRATOR_ALLOWED_TOOLS = {"teleclaude__get_context"}


class ToolSpec(TypedDict, total=False):
    """Minimal tool spec used for filtering."""

    name: str


def is_tool_allowed(role: str, tool_name: str) -> bool:
    """Return whether a tool is allowed for the given role.

    Args:
        role: The role name.
        tool_name: The tool name.

    Returns:
        True if the tool is allowed for the role.
    """
    if role == "orchestrator":
        return True
    return tool_name in NON_ORCHESTRATOR_ALLOWED_TOOLS


def filter_tool_names(role: str, tool_names: list[str]) -> list[str]:
    """Return filtered tool names for a role."""
    if role == "orchestrator":
        return tool_names
    return [name for name in tool_names if name in NON_ORCHESTRATOR_ALLOWED_TOOLS]


def filter_tool_specs(role: str, tools: list[ToolSpec]) -> list[ToolSpec]:
    """Return filtered tool specs for a role."""
    if role == "orchestrator":
        return tools
    return [tool for tool in tools if tool.get("name") in NON_ORCHESTRATOR_ALLOWED_TOOLS]


def get_allowed_tools(role: str, all_tool_names: list[str]) -> list[str]:
    """Return list of allowed tool names for a role.

    Args:
        role: The role name.
        all_tool_names: Full list of available tool names.

    Returns:
        Filtered list of tool names.
    """
    return filter_tool_names(role, all_tool_names)
