"""CLI surface schema types — TelecCommand enum, CommandAuth, Flag, CommandDef, and auth constants."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from teleclaude.constants import (
    HUMAN_ROLE_ADMIN,
    HUMAN_ROLE_CONTRIBUTOR,
    HUMAN_ROLE_CUSTOMER,
    HUMAN_ROLE_MEMBER,
    HUMAN_ROLE_NEWCOMER,
    ROLE_INTEGRATOR,
    ROLE_ORCHESTRATOR,
    ROLE_WORKER,
)


class TelecCommand(str, Enum):
    """Supported telec CLI commands."""

    SESSIONS = "sessions"
    COMPUTERS = "computers"
    PROJECTS = "projects"
    AGENTS = "agents"
    CHANNELS = "channels"
    OPERATIONS = "operations"
    INIT = "init"
    VERSION = "version"
    SYNC = "sync"
    WATCH = "watch"
    DOCS = "docs"
    TODO = "todo"
    ROADMAP = "roadmap"
    BUGS = "bugs"
    EVENTS = "events"
    AUTH = "auth"
    CONFIG = "config"
    CONTENT = "content"
    HISTORY = "history"
    MEMORIES = "memories"
    SIGNALS = "signals"


# =============================================================================
# CLI Surface Schema — single source of truth for help, completion, and docs
# =============================================================================


@dataclass(frozen=True)
class CommandAuth:
    system: frozenset[str]  # allowed system roles
    human: frozenset[str]  # allowed human roles (admin must be explicit)

    def allows(self, system_role: str | None, human_role: str | None) -> bool:
        """Check whether a caller with the given roles is authorized.

        Agent callers (system_role set) check the system set.
        Human callers (no system_role) check the human set.
        """
        if system_role is not None:
            return system_role in self.system
        return human_role in self.human if human_role is not None else False


@dataclass
class Flag:
    long: str
    short: str | None = None
    desc: str = ""
    hidden: bool = False  # hidden from main help overview, visible in subcommand help

    def as_tuple(self) -> tuple[str | None, str, str]:
        """Backward-compat tuple for completion helpers."""
        return (self.short, self.long, self.desc)


@dataclass
class CommandDef:
    desc: str
    args: str = ""  # e.g., "<slug>", "[mode] [prompt]"
    flags: list[Flag] = field(default_factory=list)
    subcommands: dict[str, CommandDef] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # extra lines for subcommand help
    examples: list[str] = field(default_factory=list)  # explicit examples when auto-generation is misleading
    hidden: bool = False  # hide from help output and completion
    standalone: bool = False  # bare invocation has behavior (not just help text)
    auth: CommandAuth | None = None

    @property
    def visible_flags(self) -> list[Flag]:
        """Flags shown in main help overview."""
        return [f for f in self.flags if not f.hidden]

    @property
    def flag_tuples(self) -> list[tuple[str | None, str, str]]:
        """All flags as tuples for completion."""
        return [f.as_tuple() for f in self.flags]

    @property
    def subcmd_tuples(self) -> list[tuple[str, str]]:
        """Subcommands as (name, desc) tuples for completion."""
        return [(name, sub.desc) for name, sub in self.subcommands.items()]


_H = Flag("--help", "-h", "Show usage information", hidden=True)

# =============================================================================
# Auth shorthand constants — used in CLI_SURFACE auth fields
# =============================================================================

_SYS_ORCH = frozenset({ROLE_ORCHESTRATOR, ROLE_INTEGRATOR})
_SYS_ALL = frozenset({ROLE_WORKER, ROLE_ORCHESTRATOR, ROLE_INTEGRATOR})
_SYS_INTG = frozenset({ROLE_INTEGRATOR})

_HR_ADMIN = frozenset({HUMAN_ROLE_ADMIN})
_HR_MEMBER = frozenset({HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER})
_HR_MEMBER_CONTRIB = frozenset({HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR})
_HR_MEMBER_CONTRIB_NEWCOMER = frozenset({HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER})
_HR_ALL_NON_ADMIN = frozenset({HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER, HUMAN_ROLE_CUSTOMER})
_HR_ALL = frozenset({HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER, HUMAN_ROLE_CUSTOMER})
