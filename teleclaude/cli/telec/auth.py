"""Authorization helpers for the telec CLI."""

from __future__ import annotations

from teleclaude.cli import CommandScope
from teleclaude.cli.telec.surface import CLI_SURFACE, CommandAuth, CommandDef

_TELEC_PREFIX = "telec "
_PATH_SEPARATOR = "."
_WORD_SEPARATOR = " "


def _resolve_command(command_path: str) -> CommandDef | None:
    """Resolve a command path to its declaration, or None if not found."""
    # Normalize: accept "sessions.start" or "telec sessions start" or "sessions start"
    path = command_path.strip()
    if path.startswith(_TELEC_PREFIX):
        path = path[len(_TELEC_PREFIX) :]
    parts = path.replace(_PATH_SEPARATOR, _WORD_SEPARATOR).split()
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
    return node


def _resolve_command_auth(command_path: str) -> CommandAuth | None:
    """Resolve a command path to its CommandAuth, or None if not found."""
    node = _resolve_command(command_path)
    return node.auth if node is not None else None


def command_scope(command_path: str) -> CommandScope | None:
    """Where a person's role is resolved for a command, or None for an unknown command path."""
    auth = _resolve_command_auth(command_path)
    return auth.scope if auth is not None else None


def is_desk_command(command_path: str) -> bool:
    """Whether a command path is declared safe for a confined help-desk session."""
    node = _resolve_command(command_path)
    return node is not None and node.desk


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
    if auth.caller_independent:
        return True
    return auth.allows(system_role, human_role)
