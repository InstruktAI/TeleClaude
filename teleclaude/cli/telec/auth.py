"""Authorization helpers for the telec CLI."""
from __future__ import annotations

from teleclaude.cli.telec.surface import CLI_SURFACE, CommandAuth


def _resolve_command_auth(command_path: str) -> CommandAuth | None:
    """Resolve a command path to its CommandAuth, or None if not found."""
    # Normalize: accept "sessions.start" or "telec sessions start" or "sessions start"
    path = command_path.strip()
    if path.startswith("telec "):
        path = path[len("telec ") :]
    parts = path.replace(".", " ").split()
    if not parts:
        return None
    node = CLI_SURFACE.get(parts[0])
    if node is None:
        return None
    for part in parts[1:]:
        if not node.subcommands:
            return None
        node = node.subcommands.get(part)
        if node is None:
            return None
    return node.auth


def is_command_allowed(
    command_path: str,
    system_role: str | None,
    human_role: str | None,
) -> bool:
    """Check whether a caller is authorized to run a CLI command.

    Agent callers (system_role set) check auth.system.
    Human callers (no system_role) check auth.human.
    Unknown command paths return False (fail closed).
    """
    auth = _resolve_command_auth(command_path)
    if auth is None:
        return False
    return auth.allows(system_role, human_role)
