"""CLI surface schema types — TelecCommand enum, CommandAuth, Flag, CommandDef, and auth constants."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import Enum, StrEnum

from teleclaude.cli import CommandScope
from teleclaude.constants import (
    HUMAN_ROLE_ADMIN,
    HUMAN_ROLE_CONTRIBUTOR,
    HUMAN_ROLE_CUSTOMER,
    HUMAN_ROLE_MEMBER,
    HUMAN_ROLE_NEWCOMER,
    ROLE_INTEGRATOR,
    ROLE_JOB_RUNNER,
    ROLE_ORCHESTRATOR,
    ROLE_TASKER,
    ROLE_WORKER,
    SystemRole,
)


class TelecCommand(str, Enum):
    """Supported telec CLI commands."""

    SESSIONS = "sessions"
    REMINDERS = "reminders"
    COMPUTERS = "computers"
    PROJECTS = "projects"
    AGENTS = "agents"
    CHANNELS = "channels"
    OPERATIONS = "operations"
    VERSION = "version"
    DOCS = "docs"
    TODO = "todo"
    BUGS = "bugs"
    JOBS = "jobs"
    EVENTS = "events"
    AUTH = "auth"
    CONFIG = "config"
    CONTENT = "content"
    HISTORY = "history"
    MEMORIES = "memories"
    SIGNALS = "signals"
    MCP = "mcp"
    CODE = "code"
    MESSAGE = "message"
    SYNC = "sync"


# =============================================================================
# CLI Surface Schema — single source of truth for help, completion, and docs
# =============================================================================


@dataclass(frozen=True)
class FlagConditionedAuth:
    """The scope and person band a command is judged at when one of its flags is present."""

    flag: str
    scope: CommandScope
    human: frozenset[str]
    scope_flag: str | None = None


@dataclass(frozen=True)
class CommandAuth:
    """Caller-independent declaration or role allow-list for a CLI command."""

    system: frozenset[str]  # allowed system roles
    human: frozenset[str]  # allowed human roles (admin must be explicit)
    caller_independent: bool = False
    scope: CommandScope = CommandScope.INVOCATION
    scope_flag: str | None = None
    when_flag: FlagConditionedAuth | None = None

    def conditioned(self, flag_present: bool) -> CommandAuth:
        """Return the declaration that applies: the flag-conditioned scope and band when its flag is present."""
        if self.when_flag is None or not flag_present:
            return self
        return replace(
            self,
            scope=self.when_flag.scope,
            human=self.when_flag.human,
            scope_flag=self.when_flag.scope_flag,
            when_flag=None,
        )

    def allows(self, system_role: str | None, human_role: str | None) -> bool:
        """Check whether a caller with the given roles is authorized.

        Agent callers (system_role set) check the system set.
        Human callers (no system_role) check the human set.
        """
        if self.caller_independent:
            return True
        if system_role is not None:
            if system_role not in self.system:
                return False
            return human_role is None or human_role in self.human
        return human_role in self.human if human_role is not None else False


class FlagArity(StrEnum):
    """How many argv tokens a declared flag consumes when recognized.

    ``SWITCH`` flags carry no value. ``VALUE`` consumes exactly one token;
    the last occurrence wins when the flag repeats. ``REPEATED`` also
    consumes one token per occurrence, but every occurrence is retained in
    order. ``GREEDY`` consumes every following token up to the next
    dash-leading token or ``--``, at least one, accumulated across
    occurrences — the shape a fixed-count option (validated by its handler)
    also uses.
    """

    SWITCH = "switch"
    VALUE = "value"
    OPTIONAL_VALUE = "optional_value"
    REPEATED = "repeated"
    GREEDY = "greedy"


@dataclass(frozen=True)
class Flag:
    """Single CLI flag definition used for help, completion, and recognition."""

    long: str
    short: str | None = None
    desc: str = ""
    hidden: bool = False  # hidden from help output and completion
    arity: FlagArity = field(kw_only=True)

    def as_tuple(self) -> tuple[str | None, str, str]:
        """Backward-compat tuple for completion helpers."""
        return (self.short, self.long, self.desc)


@dataclass(kw_only=True)
class _CommandPresentation:
    """Help-only metadata for a command."""

    notes: list[str] = field(default_factory=list)  # extra lines for subcommand help
    runtime_notes: list[str] = field(default_factory=list)  # leaf-help notes excluded from generated documentation
    default_help_note: bool = True  # synthesize a note when no explicit notes are declared
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
    literal_dash_tokens: bool = False  # accept undeclared dash-leading tokens as operands (see history search)
    desk: bool = False  # safe for a confined help-desk session; the desk allow list and desk visitor admission read it

    @property
    def visible_flags(self) -> list[Flag]:
        """Flags shown in main help overview."""
        return [f for f in self.flags if not f.hidden]

    @property
    def flag_tuples(self) -> list[tuple[str | None, str, str]]:
        """All flags as tuples for completion."""
        return [f.as_tuple() for f in self.visible_flags]

    @property
    def subcmd_tuples(self) -> list[tuple[str, str]]:
        """Subcommands as (name, desc) tuples for completion. Hidden subcommands excluded."""
        return [(name, sub.desc) for name, sub in self.subcommands.items() if not sub.hidden]


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
# Role reach groups — used in CLI_SURFACE auth fields
# =============================================================================
_WORKER_REACH = frozenset({ROLE_WORKER})
_AGENT_REACH = frozenset({ROLE_ORCHESTRATOR, ROLE_INTEGRATOR, SystemRole.COORDINATOR, ROLE_TASKER, ROLE_JOB_RUNNER})
_ORCHESTRATOR_RESERVATION = frozenset({ROLE_ORCHESTRATOR})
_INTEGRATOR_RESERVATION = frozenset({ROLE_INTEGRATOR})

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
