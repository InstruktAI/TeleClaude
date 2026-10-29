"""CLI surface schema types — TelecCommand enum, CommandAuth, Flag, CommandDef, and auth constants."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import Enum, StrEnum

from teleclaude.cli import CommandScope
from teleclaude.constants import HUMAN_ROLE_ADMIN, HUMAN_ROLE_CUSTOMER, HUMAN_ROLE_MEMBER
from teleclaude.core.roles import Capability, Role, UnknownRole, allows


class TelecCommand(str, Enum):
    """Supported telec CLI commands."""

    SESSIONS = "sessions"
    REMINDERS = "reminders"
    COMPUTERS = "computers"
    PROJECTS = "projects"
    AGENTS = "agents"
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
    REPO = "repo"
    MESSAGE = "message"
    AUDIO = "audio"
    SYNC = "sync"
    APP = "app"


class HookEntryVerb(StrEnum):
    """Git-hook entry verbs carried by the ``repo`` command family."""

    PRE_COMMIT = "pre-commit"
    POST_COMMIT = "post-commit"
    POST_MERGE = "post-merge"


class JobsSubcommand(StrEnum):
    """Closed set of subcommands on the jobs command group."""

    LIST = "list"
    STATUS = "status"
    ENABLE = "enable"
    DISABLE = "disable"
    RUN = "run"
    REPORT = "report"


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


def admits_any_caller(caller_independent: bool, desk_command: bool) -> bool:
    """Whether every caller is cleared for a command, so clearance need not resolve who calls.

    A caller-independent command is still refused to an anonymous help-desk visitor unless the
    surface declares it safe for a desk; only when both hold is the caller irrelevant.
    """
    return caller_independent and desk_command


@dataclass(frozen=True)
class CommandAuth:
    """Caller-independent declaration, or the capability and person roles a CLI command admits.

    A ``machine_account`` command is one the computer's own operating-system account operates: a caller
    outside any session is admitted to it on the installation's own computer, logged in or not, while
    a session is still judged by its capability and person band.
    """

    capability: Capability | None = None  # the one command capability admitting agent callers; None for person-only
    human: frozenset[str] = frozenset()  # allowed human roles (admin must be explicit)
    caller_independent: bool = False
    machine_account: bool = False
    scope: CommandScope = CommandScope.INVOCATION
    scope_flag: str | None = None
    when_flag: tuple[FlagConditionedAuth, ...] = ()

    def conditioned(self, present_flags: frozenset[str]) -> CommandAuth:
        """Return the declaration that applies: the first flag-conditioned scope and band whose flag is present."""
        condition = next((candidate for candidate in self.when_flag if candidate.flag in present_flags), None)
        if condition is None:
            return self
        return replace(
            self,
            scope=condition.scope,
            human=condition.human,
            scope_flag=condition.scope_flag,
            when_flag=(),
        )

    def allows(self, role: Role | UnknownRole | None, human_role: str | None) -> bool:
        """Check whether a caller with the given resolved role and person role is authorized.

        An agent caller (a resolved role) is admitted when its catalog entry reaches the command's
        capability, and then also passes the person band when it acts for a person. A recorded role
        the catalog does not name, and a person-only command, admit no agent caller. Human callers
        (no role) check the human set.
        """
        if self.caller_independent:
            return True
        if role is None:
            return human_role in self.human if human_role is not None else False
        if isinstance(role, UnknownRole) or self.capability is None or not allows(role, self.capability):
            return False
        return human_role is None or human_role in self.human


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
    addressed_at_boundary: bool = False  # the daemon boundary carries --computer; handlers never see it

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
# Person role bands — used in CLI_SURFACE auth fields
# =============================================================================
_HR_ADMIN = frozenset({HUMAN_ROLE_ADMIN})
_HR_MEMBER = frozenset({HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER})
_HR_ALL_NON_ADMIN = frozenset({HUMAN_ROLE_MEMBER, HUMAN_ROLE_CUSTOMER})
_HR_ALL = frozenset({HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CUSTOMER})
