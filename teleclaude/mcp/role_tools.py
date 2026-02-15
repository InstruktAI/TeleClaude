"""Role-based tool filtering for TeleClaude MCP.

This module defines which tools are available to different agent roles.
Filtering only applies when a role marker is present and role == worker.
"""

from typing import TypedDict

from teleclaude.constants import (
    HUMAN_ROLE_ADMIN,
    HUMAN_ROLE_CONTRIBUTOR,
    HUMAN_ROLE_CUSTOMER,
    HUMAN_ROLE_MEMBER,
    HUMAN_ROLE_NEWCOMER,
    ROLE_WORKER,
)

# Worker tool access policy.
WORKER_EXCLUDED_TOOLS = {
    "teleclaude__next_work",
    "teleclaude__next_prepare",
    "teleclaude__mark_phase",
    "teleclaude__start_session",
    "teleclaude__send_message",
    "teleclaude__run_agent_command",
    "teleclaude__escalate",
}

# Member tool access policy.
MEMBER_EXCLUDED_TOOLS = {
    "teleclaude__deploy",
    "teleclaude__end_session",
    "teleclaude__mark_agent_status",
    "teleclaude__escalate",
}

# Unauthorized tool access policy (read-only).
UNAUTHORIZED_EXCLUDED_TOOLS = {
    "teleclaude__start_session",
    "teleclaude__run_agent_command",
    "teleclaude__send_message",
    "teleclaude__send_file",
    "teleclaude__deploy",
    "teleclaude__stop_notifications",
    "teleclaude__end_session",
    "teleclaude__next_prepare",
    "teleclaude__next_work",
    "teleclaude__next_maintain",
    "teleclaude__mark_phase",
    "teleclaude__set_dependencies",
    "teleclaude__mark_agent_status",
    "teleclaude__mark_agent_unavailable",
    "teleclaude__escalate",
}

CUSTOMER_EXCLUDED_TOOLS: set[str] = (
    UNAUTHORIZED_EXCLUDED_TOOLS
    | {
        "teleclaude__list_sessions",
        "teleclaude__list_todos",
    }
) - {"teleclaude__escalate"}


class ToolSpec(TypedDict, total=False):
    """Minimal tool spec used for filtering."""

    name: str


def get_excluded_tools(role: str | None, human_role: str | None = None) -> set[str]:
    """Return set of tool names excluded for this role."""
    excluded = set()
    if role == ROLE_WORKER:
        excluded.update(WORKER_EXCLUDED_TOOLS)

    if human_role == HUMAN_ROLE_CUSTOMER:
        excluded.update(CUSTOMER_EXCLUDED_TOOLS)
        return excluded
    elif human_role in {HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER}:
        excluded.update(MEMBER_EXCLUDED_TOOLS)
    elif human_role is None:
        excluded.update(UNAUTHORIZED_EXCLUDED_TOOLS)
    elif human_role != HUMAN_ROLE_ADMIN:
        # Default to unauthorized for unknown/custom roles.
        excluded.update(UNAUTHORIZED_EXCLUDED_TOOLS)

    return excluded


def is_tool_allowed(role: str | None, tool_name: str, human_role: str | None = None) -> bool:
    """Return whether a tool is allowed for the given role.

    Args:
        role: The role name, if any.
        tool_name: The tool name.
        human_role: The human role name, if any.

    Returns:
        True if the tool is allowed for the role or no filtering applies.
    """
    return tool_name not in get_excluded_tools(role, human_role)


def filter_tool_names(role: str | None, tool_names: list[str], human_role: str | None = None) -> list[str]:
    """Return filtered tool names for a role.

    If no role marker is found, returns the original list (no filtering).
    """
    excluded = get_excluded_tools(role, human_role)
    if not excluded:
        return tool_names
    return [name for name in tool_names if name not in excluded]


def filter_tool_specs(role: str | None, tools: list[ToolSpec], human_role: str | None = None) -> list[ToolSpec]:
    """Return filtered tool specs for a role.

    If no role marker is found, returns the original list (no filtering).
    """
    excluded = get_excluded_tools(role, human_role)
    if not excluded:
        return tools
    return [tool for tool in tools if tool.get("name") not in excluded]


def get_allowed_tools(role: str | None, all_tool_names: list[str], human_role: str | None = None) -> list[str]:
    """Return list of allowed tool names for a role.

    Args:
        role: The role name, if any.
        all_tool_names: Full list of available tool names.
        human_role: The human role name, if any.

    Returns:
        Filtered list of tool names.
    """
    return filter_tool_names(role, all_tool_names, human_role)
