"""Caller-specific help visibility, composed from identity-owned decisions."""

from __future__ import annotations

from dataclasses import dataclass

from teleclaude.cli.session_auth import (
    SELF_SESSION_TARGET,
    ResolvedCliIdentity,
    cli_clearance,
    resolve_cli_identity,
)
from teleclaude.cli.telec.surface import CommandDef
from teleclaude.core.roles import Role, UnknownRole, resolve_session_role

_COMMAND_PATH_SEPARATOR = " "


@dataclass(frozen=True)
class HelpView:
    """The resolved caller's complete/restricted mode and command admission answers."""

    identity: ResolvedCliIdentity
    role: Role | UnknownRole | None
    complete: bool

    def permits(self, path: tuple[str, ...], node: CommandDef) -> bool:
        command_path = _COMMAND_PATH_SEPARATOR.join(path)
        return any(
            cli_clearance(
                command_path,
                self.identity,
                target_session_id=target,
                auth=node.auth,
                desk_command=node.desk,
            ).refusal
            is None
            for target in (None, SELF_SESSION_TARGET)
        )

    def focuses(self, node: CommandDef) -> bool:
        return isinstance(self.role, Role) and node.auth is not None and node.auth.capability in self.role.capabilities


def resolve_help_view() -> HelpView:
    """Resolve the local CLI caller and its role once for one help request."""
    identity = resolve_cli_identity()
    role = resolve_session_role(identity.role, identity.session_id)
    complete = identity.role is None or (isinstance(role, Role) and role.full_reach)
    return HelpView(identity=identity, role=role, complete=complete)
