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

# Worker tool access policy (whitelist).
# Only these clearance-gated tools are permitted for worker sessions.
# Tools without clearance gates (telec docs, telec version, etc.) are unaffected.
WORKER_ALLOWED_TOOLS = {
    "telec sessions send",
    "telec sessions result",
    "telec sessions file",
    "telec sessions widget",
    "telec sessions tail",
    "telec sessions list",
    "telec sessions unsubscribe",
    "telec sessions escalate",
    "telec channels list",
    "telec channels publish",
    "telec agents availability",
    "telec computers list",
    "telec projects list",
    "telec operations get",
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
    "telec todo mark-phase",
    "telec todo set-deps",
    "telec operations get",
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


def _get_human_excluded_tools(human_role: str | None) -> set[str]:
    """Return excluded tools based on human role only."""
    if human_role == HUMAN_ROLE_CUSTOMER:
        return CUSTOMER_EXCLUDED_TOOLS
    if human_role in {HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER}:
        return MEMBER_EXCLUDED_TOOLS
    if human_role is None or human_role != HUMAN_ROLE_ADMIN:
        return UNAUTHORIZED_EXCLUDED_TOOLS
    return set()


def get_excluded_tools(role: str | None, human_role: str | None = None) -> set[str]:  # noqa: ARG001
    """Return set of tool names excluded for this role.

    Note: worker enforcement uses a whitelist via is_tool_allowed().
    This function returns human-role exclusions only.
    """
    return _get_human_excluded_tools(human_role)


def is_tool_allowed(role: str | None, tool_name: str, human_role: str | None = None) -> bool:
    """Return whether a tool is allowed for the given role.

    Worker sessions use a whitelist: only tools in WORKER_ALLOWED_TOOLS pass.
    Human roles use exclusion sets. The two layers are mutually exclusive —
    workers are system-level sessions and not subject to human role restrictions.
    """
    if role == ROLE_WORKER:
        return tool_name in WORKER_ALLOWED_TOOLS
    return tool_name not in _get_human_excluded_tools(human_role)


def filter_tool_names(role: str | None, tool_names: list[str], human_role: str | None = None) -> list[str]:
    """Return filtered tool names for a role."""
    return [n for n in tool_names if is_tool_allowed(role, n, human_role)]


def filter_tool_specs(role: str | None, tools: list[ToolSpec], human_role: str | None = None) -> list[ToolSpec]:
    """Return filtered tool specs for a role."""
    return [t for t in tools if is_tool_allowed(role, t.get("name", ""), human_role)]


def get_allowed_tools(role: str | None, all_tool_names: list[str], human_role: str | None = None) -> list[str]:
    """Return list of allowed tool names for a role."""
    return filter_tool_names(role, all_tool_names, human_role)
