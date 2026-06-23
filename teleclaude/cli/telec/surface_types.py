"""CLI surface schema types — TelecCommand enum, CommandAuth, Flag, CommandDef, and auth constants."""

from __future__ import annotations

import re
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
    ROLE_SYSTEM,
    ROLE_WORKER,
)


class TelecCommand(str, Enum):
    """Supported telec CLI commands."""

    SESSIONS = "sessions"
    COMPUTERS = "computers"
    PROJECTS = "projects"
    COMPANIES = "companies"
    AGENTS = "agents"
    CHANNELS = "channels"
    OPERATIONS = "operations"
    VERSION = "version"
    SYNC = "sync"
    DOCS = "docs"
    TODO = "todo"
    BUGS = "bugs"
    EVENTS = "events"
    AUTH = "auth"
    CONFIG = "config"
    CONTENT = "content"
    HISTORY = "history"
    MEMORIES = "memories"
    SIGNALS = "signals"
    CODE = "code"
    CONTEXT = "context"


# =============================================================================
# CLI Surface Schema — single source of truth for help, completion, and docs
# =============================================================================


@dataclass(frozen=True)
class CommandAuth:
    """Role allow-list for a CLI command."""

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
    """Single CLI flag definition used for help and completion."""

    long: str
    short: str | None = None
    desc: str = ""
    hidden: bool = False  # hidden from main help overview, visible in subcommand help

    def as_tuple(self) -> tuple[str | None, str, str]:
        """Backward-compat tuple for completion helpers."""
        return (self.short, self.long, self.desc)


@dataclass(kw_only=True)
class _CommandPresentation:
    """Help-only metadata for a command."""

    notes: list[str] = field(default_factory=list)  # extra lines for subcommand help
    examples: list[str] = field(default_factory=list)  # curated examples shown in help output
    hidden: bool = False  # hide from help output and completion
    standalone: bool = False  # bare invocation has behavior (not just help text)


@dataclass
class CommandDef(_CommandPresentation):
    """Declarative command schema for help, completion, and dispatch."""

    desc: str
    args: str = ""  # e.g., "<slug>", "[mode] [prompt]"
    flags: list[Flag] = field(default_factory=list)
    subcommands: dict[str, CommandDef] = field(default_factory=dict)
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
        """Subcommands as (name, desc) tuples for completion. Hidden subcommands excluded."""
        return [(name, sub.desc) for name, sub in self.subcommands.items() if not sub.hidden]


_H = Flag("--help", "-h", "Show usage information", hidden=True)

# Shared flag definitions reused across multiple CommandDef entries.
# When the same `Flag(...)` literal appears in more than one command, define it
# here and reference the constant — keep the surface single-source-of-truth.
_FLAG_COMPUTER = Flag("--computer", "-c", "Target computer (optional; defaults to local)")
_FLAG_AGENT = Flag("--agent", desc="Agent: claude, gemini, codex")
_FLAG_MODE = Flag("--mode", desc="Thinking mode: fast, med, slow")
_FLAG_DETACH = Flag(
    "--detach",
    desc="Fire-and-forget: inherit context but skip listener registration",
    hidden=True,
)
_FLAG_PROJECT_PATH = Flag("--project", desc="Project directory path (optional; defaults to cwd)")
_FLAG_PROJECT_FILTER = Flag("--project", desc="Filter by project name")
_FLAG_PROJECT_TRUSTED = Flag("--project", desc="Project name (from trusted_dirs)")
_FLAG_SESSION = Flag("--session", "-s", "Session ID")
_FLAG_THINKING = Flag("--thinking", desc="Include thinking blocks")
_FLAG_LIMIT_20 = Flag("--limit", desc="Max results (default: 20)")
_FLAG_AFTER_DEPS = Flag("--after", desc="Comma-separated dependency slugs")


def strip_hidden_flag_tokens(args: str, flags: list[Flag]) -> str:
    """Remove ``[--<long>]`` and ``[--<long> <value>]`` tokens for hidden flags
    from a hand-written usage args string.

    The args field on ``CommandDef`` is currently a literal string maintained
    alongside the ``flags`` list. ``hidden=True`` on a flag must also suppress
    that flag from the rendered usage line — this helper performs the strip
    so both renderers (``help.py`` and ``surface.py::_render_command``) honor
    the contract uniformly.
    """
    if not args:
        return args
    result = args
    for flag in flags:
        if not flag.hidden:
            continue
        pattern = rf"\s*\[{re.escape(flag.long)}(?:\s+<[^>]+>)?\]"
        result = re.sub(pattern, "", result)
    return result.strip()


# =============================================================================
# Auth shorthand constants — used in CLI_SURFACE auth fields
# =============================================================================

_SYS_ORCH = frozenset({ROLE_SYSTEM, ROLE_ORCHESTRATOR, ROLE_INTEGRATOR})
_SYS_ALL = frozenset({ROLE_WORKER, ROLE_SYSTEM, ROLE_ORCHESTRATOR, ROLE_INTEGRATOR})
_SYS_INTG = frozenset({ROLE_INTEGRATOR})

_HR_ADMIN = frozenset({HUMAN_ROLE_ADMIN})
_HR_MEMBER = frozenset({HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER})
_HR_MEMBER_CONTRIB = frozenset({HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR})
_HR_MEMBER_CONTRIB_NEWCOMER = frozenset(
    {HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER}
)
_HR_ALL_NON_ADMIN = frozenset({HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER, HUMAN_ROLE_CUSTOMER})
_HR_ALL = frozenset(
    {HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER, HUMAN_ROLE_CUSTOMER}
)
