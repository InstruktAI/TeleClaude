"""Role-based tool access filtering.

Tool name filtering is derived from CLI_SURFACE CommandAuth entries.
The legacy hardcoded exclusion sets (WORKER_ALLOWED_TOOLS, MEMBER_EXCLUDED_TOOLS,
UNAUTHORIZED_EXCLUDED_TOOLS) have been retired. Authorization uses
is_command_allowed() from teleclaude.cli.telec as the single source of truth.
"""

from collections.abc import Iterator

from typing_extensions import TypedDict

from teleclaude.cli.telec.surface import CommandDef


class ToolSpec(TypedDict, total=False):
    """Minimal tool spec used for filtering."""

    name: str


def _collect_gated_paths() -> list[str]:
    """Enumerate all CLI command paths that have CommandAuth (clearance-gated)."""
    from teleclaude.cli.telec import CLI_SURFACE

    def _walk(surface: dict[str, CommandDef], prefix: str = "") -> Iterator[str]:
        for name, cmd in surface.items():
            path = f"{prefix} {name}".strip() if prefix else name
            if cmd.subcommands:
                yield from _walk(cmd.subcommands, path)
            elif cmd.auth is not None:
                yield path

    return list(_walk(CLI_SURFACE))


def get_excluded_tools(role: str | None, human_role: str | None = None) -> set[str]:
    """Return set of tool names excluded for this human role.

    Derived from CLI_SURFACE CommandAuth entries — human-role filtering only.
    The role parameter is accepted for API compatibility but unused here;
    system-role enforcement is handled by _is_tool_denied() in daemon auth.
    """
    from teleclaude.cli.telec import is_command_allowed

    excluded = set()
    for path in _collect_gated_paths():
        tool = f"telec {path}"
        # Check with system_role=None (treated as orchestrator — TUI/terminal callers).
        if not is_command_allowed(path, None, human_role):
            excluded.add(tool)
    return excluded


def filter_tool_names(role: str | None, tool_names: list[str], human_role: str | None = None) -> list[str]:
    """Return filtered tool names for a role."""
    from teleclaude.cli.telec import is_command_allowed

    result = []
    for name in tool_names:
        path = name[len("telec ") :] if name.startswith("telec ") else name
        if is_command_allowed(path, role, human_role):
            result.append(name)
    return result


def filter_tool_specs(role: str | None, tools: list[ToolSpec], human_role: str | None = None) -> list[ToolSpec]:
    """Return filtered tool specs for a role."""
    from teleclaude.cli.telec import is_command_allowed

    result = []
    for t in tools:
        name = t.get("name", "")
        path = name[len("telec ") :] if name.startswith("telec ") else name
        if is_command_allowed(path, role, human_role):
            result.append(t)
    return result


def get_allowed_tools(role: str | None, all_tool_names: list[str], human_role: str | None = None) -> list[str]:
    """Return list of allowed tool names for a role."""
    return filter_tool_names(role, all_tool_names, human_role)
