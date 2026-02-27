"""Role-based tool access filtering."""

from typing_extensions import TypedDict

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
    "telec todo work",
    "telec todo prepare",
    "telec todo mark-phase",
    "telec sessions start",
    "telec sessions send",
    "telec sessions run",
    "telec sessions escalate",
}

# Member tool access policy.
MEMBER_EXCLUDED_TOOLS = {
    "telec sessions end",
    "telec agents status",
    "telec sessions escalate",
}

# Unauthorized tool access policy (read-only).
UNAUTHORIZED_EXCLUDED_TOOLS = {
    "telec sessions start",
    "telec sessions run",
    "telec sessions send",
    "telec sessions file",
    "telec sessions unsubscribe",
    "telec sessions end",
    "telec todo prepare",
    "telec todo work",
    "telec todo maintain",
    "telec todo mark-phase",
    "telec todo set-deps",
    "telec agents status",
    "telec sessions escalate",
}

CUSTOMER_EXCLUDED_TOOLS: set[str] = (
    UNAUTHORIZED_EXCLUDED_TOOLS
    | {
        "telec sessions list",
        "telec roadmap list",
        "telec channels publish",
        "telec channels list",
    }
) - {"telec sessions escalate"}


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
    if human_role in {HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER}:
        excluded.update(MEMBER_EXCLUDED_TOOLS)
    elif human_role is None:
        excluded.update(UNAUTHORIZED_EXCLUDED_TOOLS)
    elif human_role != HUMAN_ROLE_ADMIN:
        # Default to unauthorized for unknown/custom roles.
        excluded.update(UNAUTHORIZED_EXCLUDED_TOOLS)

    return excluded


def is_tool_allowed(role: str | None, tool_name: str, human_role: str | None = None) -> bool:
    """Return whether a tool is allowed for the given role."""
    return tool_name not in get_excluded_tools(role, human_role)


def filter_tool_names(role: str | None, tool_names: list[str], human_role: str | None = None) -> list[str]:
    """Return filtered tool names for a role."""
    excluded = get_excluded_tools(role, human_role)
    if not excluded:
        return tool_names
    return [name for name in tool_names if name not in excluded]


def filter_tool_specs(role: str | None, tools: list[ToolSpec], human_role: str | None = None) -> list[ToolSpec]:
    """Return filtered tool specs for a role."""
    excluded = get_excluded_tools(role, human_role)
    if not excluded:
        return tools
    return [tool for tool in tools if tool.get("name") not in excluded]


def get_allowed_tools(role: str | None, all_tool_names: list[str], human_role: str | None = None) -> list[str]:
    """Return list of allowed tool names for a role."""
    return filter_tool_names(role, all_tool_names, human_role)
