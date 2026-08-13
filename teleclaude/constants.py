"""Constants used across TeleClaude.

This module defines shared constants to ensure consistency.
"""

import functools
import os
import re
from dataclasses import dataclass
from enum import Enum, StrEnum

# Taxonomy Types (single source of truth)
# Used for snippet categorization and get_context filtering
TAXONOMY_TYPES = ["principle", "concept", "policy", "procedure", "design", "spec", "adr"]

# Display suffix mapping for snippet types
TYPE_SUFFIX = {
    "policy": "Policy",
    "procedure": "Procedure",
    "principle": "Principle",
    "concept": "Concept",
    "design": "Design",
    "spec": "Spec",
    "adr": "ADR",
}

# API socket configuration
API_SOCKET_PATH = "/tmp/teleclaude-api.sock"
MCP_SOCKET_PATH = "/tmp/teleclaude.sock"

# Internal configuration (not user-configurable)
DIRECTORY_CHECK_INTERVAL = 5  # Seconds between directory change checks
OUTPUT_CADENCE_S = 1.0
VOICE_TRANSCRIPTION_TIMEOUT_S = 120.0
# Conservative cross-adapter edit ceiling; longer voice results use overflow send delivery.
VOICE_TRANSCRIPTION_NOTICE_EDIT_MAX_CHARS = 2000
VOICE_TRANSCRIPTION_RECOVERY_MAX_ATTEMPTS = 3
VOICE_TRANSCRIPTION_STATE_PENDING = "pending"
VOICE_TRANSCRIPTION_STATE_IN_PROGRESS = "in_progress"
VOICE_TRANSCRIPTION_STATE_SUCCEEDED = "succeeded"
VOICE_TRANSCRIPTION_STATE_FAILED = "failed"
VOICE_TRANSCRIPTION_STATE_INTERRUPTED = "interrupted"
VOICE_TRANSCRIPTION_RECOVERABLE_STATES = (
    VOICE_TRANSCRIPTION_STATE_PENDING,
    VOICE_TRANSCRIPTION_STATE_IN_PROGRESS,
    VOICE_TRANSCRIPTION_STATE_INTERRUPTED,
)
VOICE_TRANSCRIPTION_TERMINAL_STATES = (
    VOICE_TRANSCRIPTION_STATE_SUCCEEDED,
    VOICE_TRANSCRIPTION_STATE_FAILED,
)
HELP_DESK_SUBDIR = ".teleclaude/help-desk"
WHATSAPP_API_VERSION = "v21.0"
UI_MESSAGE_MAX_CHARS = 3900  # Char budget for content selection (format + fit)
TELEGRAM_MAX_MESSAGE_BYTES = 4096  # Telegram API hard limit for message text

# Common protocol tokens (internal canonical strings)
MAIN_MODULE = "__main__"
LOCAL_COMPUTER = "local"
ENV_ENABLE = "1"
INTEGRATOR_GITOP_ENV = "TELECLAUDE_INTEGRATOR_GITOP"
# Marker prefixing a manual lifecycle operation's result text when the runner
# was not dispatched (skipped, invalid kind, or a claim conflict). A completed
# operation carrying this marker is a refusal, not a success.
RUNNER_NOT_DISPATCHED = "RUNNER_NOT_DISPATCHED"

# System roles
ROLE_SYSTEM = "system"
ROLE_ORCHESTRATOR = "orchestrator"
ROLE_WORKER = "worker"
ROLE_INTEGRATOR = "integrator"
ROLE_TASKER = "tasker"
# A job-runner session (a recurring scheduled job, e.g. log_bug_hunter or a
# generic cron agent job) is the only role band permitted a no-human lineage
# root at todo/bug creation — see project/spec/domain/workflow.
ROLE_JOB_RUNNER = "job_runner"


class DriverLaunchClass(StrEnum):
    """How a session-create launch is treated by the driver-start dedup guard.

    A create door always writes a new session row, so the guard keys on what the
    requested launch IS — classified from its slash command:

    - ``ORCHESTRATOR``: a lifecycle orchestrator driver (``/next-prepare``,
      ``/next-work``). Refused against ANY live holder, caller-independent — a
      second orchestrator row for a driven slug is never legitimate.
    - ``TASK_LANE``: the task-lane driver (``/next-run-task``). Refused against a
      live ``active_runner`` for the slug.
    - ``REVIEWER``: a reviewer worker (``/next-review-build``,
      ``/next-review-plan``, ``/next-review-architecture``,
      ``/next-review-commits``). Refused against a live reviewer already open
      for the same review subject — a reviewer's output is a verdict, and a
      second concurrent instance produces a contradictory one rather than a
      legitimate concurrent mutation.
    - ``WORKER_CHILD``: every other launch — the producing workers (builder,
      fixer, finalizer, intaker, planner, drift analyzer). An orchestrator and
      the workers it spawns legitimately share ``working_slug``, so these are
      never deduped.
    """

    ORCHESTRATOR = "orchestrator"
    TASK_LANE = "task_lane"
    REVIEWER = "reviewer"
    WORKER_CHILD = "worker_child"


# Human identity roles
HUMAN_ROLE_ADMIN = "admin"
HUMAN_ROLE_MEMBER = "member"
HUMAN_ROLE_CONTRIBUTOR = "contributor"
HUMAN_ROLE_NEWCOMER = "newcomer"
HUMAN_ROLE_CUSTOMER = "customer"
HUMAN_ROLES = (HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER, HUMAN_ROLE_CUSTOMER)

SNIPPET_VISIBILITY_PUBLIC = "public"
SNIPPET_VISIBILITY_INTERNAL = "internal"
SNIPPET_VISIBILITY_VALUES = (SNIPPET_VISIBILITY_PUBLIC, SNIPPET_VISIBILITY_INTERNAL)


class TodoStatus(StrEnum):
    """Todo table `status` column and projected todo status (CLI/API/TUI)."""

    DRAFT = "draft"
    PENDING = "pending"
    ACTIVE = "active"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    ICEBOX = "icebox"
    DELIVERED = "delivered"
    REMOVED = "removed"


class IntegrationPhase(StrEnum):
    """Canonical integration-phase pointer values."""

    STARTED = "started"
    DELIVERED = "delivered"


class HookSourceKind(StrEnum):
    """Classify a hook invocation by its managed-session lineage."""

    MANAGED_PRIMARY = "managed-primary"
    MANAGED_DESCENDANT = "managed-descendant"
    MANAGED_TEARDOWN = "managed-teardown"
    HEADLESS = "headless"


class MarkerState(StrEnum):
    """Represent whether the inherited session-identity marker is usable."""

    ABSENT = "absent"
    INVALID = "invalid"
    VALID = "valid"


# Canonical "slug not found" wording, shared by every daemon-API and CLI
# surface that reports a slug absent from the resolved todos.db.
SLUG_NOT_FOUND_DETAIL = "slug '{slug}' not found in todo list"

# Distinct from SLUG_NOT_FOUND_DETAIL: unfreeze fails when the slug exists but
# is not currently iceboxed (e.g. active) — "not found in todo list" would be
# false in that case, since the slug plainly is in the todo list.
SLUG_NOT_IN_ICEBOX_DETAIL = "slug '{slug}' not found in icebox"


# Todo artifact names — canonical values for the `name` column of todo_artifacts.
ARTIFACT_INPUT = "input"
ARTIFACT_PRD = "prd"
ARTIFACT_REQUIREMENTS = "requirements"
ARTIFACT_ARCHITECTURE = "architecture"
ARTIFACT_DIAGNOSIS = "diagnosis"
ARTIFACT_INVESTIGATION = "investigation"
ARTIFACT_IMPLEMENTATION_PLAN = "implementation-plan"
ARTIFACT_TASK_PLAN = "task-plan"
# The kind=task lane's continuity / restart-idempotency record: read on start,
# appended with dated entries per firing, kept lean. A run-phase product — not
# prepare-owned, not drift-tracked, not lifecycle-relevant.
ARTIFACT_LOG = "log"
# DEPRECATED: bug reports now live in the universal "input" artifact (kind=bug is
# authoritative). Retained only for READ/REMOVE of pre-collapse todos; the on-open
# migration `_migrate_bug_artifact_to_input` renames existing rows to "input".
ARTIFACT_BUG = "bug"
ARTIFACT_QUALITY_CHECKLIST = "quality-checklist"
ARTIFACT_DESIGN_SPEC = "design-spec"
ARTIFACT_DEFERRALS = "deferrals"
# Retired requirements artifacts remain registered for historical reads, diffs,
# and removals, but are excluded from the writable artifact surface below.
ARTIFACT_REQUIREMENTS_REVIEW_FINDINGS = "requirements-review-findings"
ARTIFACT_PRD_REVIEW_FINDINGS = "prd-review-findings"
ARTIFACT_ARCHITECTURE_REVIEW_FINDINGS = "architecture-review-findings"
ARTIFACT_PLAN_REVIEW_FINDINGS = "plan-review-findings"
ARTIFACT_REVIEW_FINDINGS = "review-findings"
# TodoState state-dict keys for artifacts. Separate namespace from ARTIFACT_* names:
# state keys use underscores ("implementation_plan"), artifact names use hyphens ("implementation-plan").
# Convert via teleclaude.core.next_machine.artifacts.artifact_name_to_state_key.
STATE_KEY_INPUT = "input"
STATE_KEY_PRD = "prd"
STATE_KEY_REQUIREMENTS = "requirements"
STATE_KEY_ARCHITECTURE = "architecture"
STATE_KEY_DIAGNOSIS = "diagnosis"
STATE_KEY_IMPLEMENTATION_PLAN = "implementation_plan"
STATE_KEY_TASK_PLAN = "task_plan"

ARTIFACT_NAMES: frozenset[str] = frozenset(
    {
        ARTIFACT_INPUT,
        ARTIFACT_PRD,
        ARTIFACT_REQUIREMENTS,
        ARTIFACT_ARCHITECTURE,
        ARTIFACT_DIAGNOSIS,
        ARTIFACT_INVESTIGATION,
        ARTIFACT_IMPLEMENTATION_PLAN,
        ARTIFACT_TASK_PLAN,
        ARTIFACT_LOG,
        ARTIFACT_BUG,
        ARTIFACT_QUALITY_CHECKLIST,
        ARTIFACT_DESIGN_SPEC,
        ARTIFACT_DEFERRALS,
        ARTIFACT_REQUIREMENTS_REVIEW_FINDINGS,
        ARTIFACT_PRD_REVIEW_FINDINGS,
        ARTIFACT_ARCHITECTURE_REVIEW_FINDINGS,
        ARTIFACT_PLAN_REVIEW_FINDINGS,
        ARTIFACT_REVIEW_FINDINGS,
    }
)

ARTIFACT_NAMES_RETIRED: frozenset[str] = frozenset(
    {
        ARTIFACT_BUG,
        ARTIFACT_REQUIREMENTS,
        ARTIFACT_REQUIREMENTS_REVIEW_FINDINGS,
        ARTIFACT_INVESTIGATION,
    }
)

ARTIFACT_NAMES_WRITABLE: frozenset[str] = ARTIFACT_NAMES - ARTIFACT_NAMES_RETIRED

# The prepare-owned derivation-root artifacts. Writable only by a prepare-phase
# writer (a prepare-orchestrator, human-identity session, or roleless operator
# session) that is not a different live claim holder; writes are versioned and
# do not claim the slug themselves. See the Write authority contract in
# docs/project/spec/feature/workflow/artifact-versioning.md.
PREPARE_ARTIFACT_NAMES: frozenset[str] = frozenset(
    {
        ARTIFACT_INPUT,
        ARTIFACT_PRD,
        ARTIFACT_ARCHITECTURE,
        ARTIFACT_DIAGNOSIS,
        ARTIFACT_IMPLEMENTATION_PLAN,
    }
)


class ResultStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SENT = "sent"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class ComputerStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    RESTARTING = "restarting"


class SystemCommand(str, Enum):
    HEALTH_CHECK = "health_check"
    EXIT = "exit"


class SlashCommand(str, Enum):
    """Canonical slash commands dispatched to agent sessions."""

    NEXT_BUILD = "next-build"
    NEXT_REVIEW_BUILD = "next-review-build"
    NEXT_REVIEW_PRD = "next-review-prd"
    NEXT_REVIEW_PLAN = "next-review-plan"
    NEXT_REVIEW_ARCHITECTURE = "next-review-architecture"
    NEXT_REVIEW_COMMITS = "next-review-commits"
    NEXT_FINALIZE = "next-finalize"
    NEXT_PREPARE_INTAKE = "next-prepare-intake"
    NEXT_PREPARE_ARCHITECTURE = "next-prepare-architecture"
    NEXT_PREPARE_DIAGNOSE = "next-prepare-diagnose"
    NEXT_PREPARE_PLAN = "next-prepare-plan"
    NEXT_PREPARE_TASK = "next-prepare-task"
    NEXT_EMULATE_PO = "next-emulate-po"
    NEXT_DRIFT_ANALYZE = "next-drift-analyze"
    NEXT_PREPARE = "next-prepare"
    NEXT_WORK = "next-work"
    NEXT_RUN_TASK = "next-run-task"
    NEXT_INTEGRATE = "next-integrate"
    NEXT_CREATE_ART = "next-create-art"
    NEXT_CREATE_HTML = "next-create-html"


# Canonical `/next-*` commands that may run without a todo slug: the prepare
# orchestrator and integrator can select work themselves, and review-commits is
# bound to commit SHAs rather than a slug. The dispatch required-slug gate and
# Codex startup rewrite read this single set so they cannot disagree on which
# commands may run argless.
NON_SLUG_BOUND_COMMANDS = frozenset(
    {SlashCommand.NEXT_PREPARE, SlashCommand.NEXT_INTEGRATE, SlashCommand.NEXT_REVIEW_COMMITS}
)


class JobRole(str, Enum):
    """Canonical job roles for sessions spawned by slash commands."""

    BUILDER = "builder"
    REVIEWER = "reviewer"
    FINALIZER = "finalizer"
    INTAKER = "intaker"
    PLANNER = "planner"
    DIAGNOSER = "diagnoser"
    ARCHITECT = "architect"
    ARCHITECTURE_REVIEWER = "architecture-reviewer"
    TASK_PREPARER = "task-preparer"
    TASK_RUNNER = "task-runner"
    DRIFT_ANALYZER = "drift-analyzer"
    PO_EMULATOR = "po-emulator"
    PREPARE_ORCHESTRATOR = "prepare-orchestrator"
    WORK_ORCHESTRATOR = "work-orchestrator"
    CREATE_ORCHESTRATOR = "create-orchestrator"
    ARTIST = "artist"
    FRONTENDER = "frontender"
    INTEGRATOR = "integrator"


# Maps slash commands to the (system_role, job_role) a session running that command holds.
# Used both by run_slash_command() internally and exported for api_server.py.
#
# Most prepare drafting phases (intake, architecture, plan) are loaded inline by the
# prepare orchestrator itself — `_load_procedure`, never `_dispatch_worker` — so the
# session running them IS the orchestrator, and they carry ROLE_ORCHESTRATOR because the
# role a command confers must match the session that actually runs it. Diagnose is the
# named exception: it is dispatched to a cross-model peer, so the session running it is a
# worker for fleet classification, while its job still names what it authors. The
# prepare-author write predicate (`PREPARE_AUTHOR_JOB_ROLES`) recognizes the job
# regardless of which system role carries it.
COMMAND_ROLE_MAP: dict[SlashCommand, tuple[str, JobRole]] = {
    SlashCommand.NEXT_BUILD: (ROLE_WORKER, JobRole.BUILDER),
    SlashCommand.NEXT_REVIEW_BUILD: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.NEXT_REVIEW_PRD: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.NEXT_REVIEW_PLAN: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.NEXT_REVIEW_ARCHITECTURE: (ROLE_WORKER, JobRole.ARCHITECTURE_REVIEWER),
    SlashCommand.NEXT_REVIEW_COMMITS: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.NEXT_CREATE_ART: (ROLE_WORKER, JobRole.ARTIST),
    SlashCommand.NEXT_CREATE_HTML: (ROLE_WORKER, JobRole.FRONTENDER),
    SlashCommand.NEXT_FINALIZE: (ROLE_WORKER, JobRole.FINALIZER),
    SlashCommand.NEXT_PREPARE_INTAKE: (ROLE_ORCHESTRATOR, JobRole.INTAKER),
    SlashCommand.NEXT_PREPARE_ARCHITECTURE: (ROLE_ORCHESTRATOR, JobRole.ARCHITECT),
    SlashCommand.NEXT_PREPARE_DIAGNOSE: (ROLE_WORKER, JobRole.DIAGNOSER),
    SlashCommand.NEXT_PREPARE_PLAN: (ROLE_ORCHESTRATOR, JobRole.PLANNER),
    SlashCommand.NEXT_PREPARE_TASK: (ROLE_TASKER, JobRole.TASK_PREPARER),
    SlashCommand.NEXT_EMULATE_PO: (ROLE_WORKER, JobRole.PO_EMULATOR),
    SlashCommand.NEXT_DRIFT_ANALYZE: (ROLE_WORKER, JobRole.DRIFT_ANALYZER),
    SlashCommand.NEXT_PREPARE: (ROLE_ORCHESTRATOR, JobRole.PREPARE_ORCHESTRATOR),
    SlashCommand.NEXT_WORK: (ROLE_ORCHESTRATOR, JobRole.WORK_ORCHESTRATOR),
    SlashCommand.NEXT_RUN_TASK: (ROLE_TASKER, JobRole.TASK_RUNNER),
    SlashCommand.NEXT_INTEGRATE: (ROLE_INTEGRATOR, JobRole.INTEGRATOR),
}

# The launch commands whose session is a dispatched worker — one derivation of the role
# map, shared by everything that has to tell worker noise from the sessions that drive
# the work. A command absent here is not a worker, so an unmapped or retired command
# stays visible rather than disappearing on a naming accident.
WORKER_COMMANDS: frozenset[str] = frozenset(
    command.value for command, role_info in COMMAND_ROLE_MAP.items() if role_info[0] == ROLE_WORKER
)

# The job roles the prepare lifecycle confers on a session that derives a prepare
# artifact (input, prd, architecture, diagnosis, implementation-plan). Read by
# `refuse_non_prepare_writer` in place of a single-job equality check, because
# diagnose dispatches its author as a worker while every other prepare phase still
# runs inline as the orchestrator — the gate recognizes the authoring job, not the
# system role that happens to carry it.
PREPARE_AUTHOR_JOB_ROLES: frozenset[str] = frozenset(
    {
        JobRole.PREPARE_ORCHESTRATOR.value,
        JobRole.INTAKER.value,
        JobRole.ARCHITECT.value,
        JobRole.DIAGNOSER.value,
        JobRole.PLANNER.value,
    }
)


class Platform(str, Enum):
    DARWIN = "darwin"


# Redis payload message types
REDIS_MSG_SYSTEM = "system"

# Redis event types
EVENT_NEW_SESSION = "new_session"
EVENT_END_SESSION = "end_session"

# Output stream markers
OUTPUT_COMPLETE_MARKER = "[Output Complete]"
OUTPUT_SYSTEM_PREFIX = "["
OUTPUT_HOURGLASS_MARKER = "⏳"
# File suffixes
# (Boundary formats keep literals at parse sites.)

# JSON field names (internal normalized schema)
FIELD_KIND = "kind"
FIELD_ORIGIN_METADATA = "origin_metadata"
FIELD_COMPUTER = "computer"
FIELD_COMMAND = "command"


# System message prefix — all daemon-injected messages use this prefix.
TELECLAUDE_SYSTEM_PREFIX = "[TeleClaude"


def format_system_message(label: str, content: str = "") -> str:
    """Format a daemon-injected system message with the canonical TeleClaude prefix.

    Returns ``[TeleClaude {label}]`` when no content is given, or
    ``[TeleClaude {label}]\\n\\n{content}`` when content is provided.
    """
    header = f"[TeleClaude {label}]"
    if content:
        return f"{header}\n\n{content.strip()}"
    return header


# Checkpoint injection
CHECKPOINT_PREFIX = "[TeleClaude Checkpoint] - "
CHECKPOINT_MESSAGE = (
    f"{CHECKPOINT_PREFIX}Continue or validate your work if needed. "
    "Perform checkpoint housekeeping silently, then send a short user-relevant debrief without mentioning checkpoint chores. "
    "Any truly interesting memories to be created that meet our criteria? "
    "(DON'T abuse it as work log!) If everything that is expected of you is done, do not respond."
)

# Max chars to capture from each tool result snippet in the transcript timeline
CHECKPOINT_RESULT_SNIPPET_MAX_CHARS = 500
# Threshold for wide blast radius observation
CHECKPOINT_BLAST_RADIUS_THRESHOLD = 3

# Sent to the agent after a restart (self-restart or maintenance auto-restore)
# once the TUI prompt is ready. The agent has full context via --resume; this
# is just a nudge to either continue in-flight work or stay idle.
RESTART_CONTINUATION_STIMULUS = "Session restarted. Continue pending work or remain idle."


@functools.lru_cache(maxsize=512)
def _compile_glob(pattern: str) -> re.Pattern[str]:
    """Compile a glob pattern with ** support to a compiled regex.

    Semantics:
    - **/  → zero or more path segments (including their trailing /)
    - **   at end → zero or more chars including /
    - *    → within a single path segment (no /)
    - ?    → a single non-separator char
    """
    regex: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                if i + 2 < n and pattern[i + 2] == "/":
                    # **/ → zero or more path segments
                    regex.append("(?:.*/)?")
                    i += 3
                else:
                    # ** at end of pattern → any chars including /
                    regex.append(".*")
                    i += 2
            else:
                # * → within-segment wildcard
                regex.append("[^/]*")
                i += 1
        elif c == "?":
            regex.append("[^/]")
            i += 1
        else:
            regex.append(re.escape(c))
            i += 1
    return re.compile("".join(regex) + r"\Z")


def _glob_matches(path: str, pattern: str) -> bool:  # pyright: ignore[reportUnusedFunction]
    """Return True if path matches the glob pattern (** support, * within segment)."""
    return bool(_compile_glob(pattern).match(path))


@dataclass(frozen=True)
class CheckpointAction:
    """A single maintenance action in the checkpoint registry (the verb).

    Evidence, gating, ordering, and the command all live on the action, never on
    a binding — so many bindings may trigger one action while its suppression,
    branch-gating, and surface order are defined exactly once. ``run`` and
    ``evidence`` may carry the ``{slug}`` placeholder, filled from the project's
    ``project_slug`` when the effective model is loaded; ``run`` may carry the
    ``{window}`` placeholder, filled with the elapsed-time log window at surface.
    """

    id: str
    run: str
    evidence: tuple[str, ...] = ()
    main_only: bool = False
    precedence: int = 0
    evidence_must_follow_last_mutation: bool = False

    def effective_evidence(self) -> tuple[str, ...]:
        """Evidence substrings proving the action ran; defaults to ``[run]``."""
        return self.evidence if self.evidence else (self.run,)


@dataclass(frozen=True)
class CheckpointScope:
    """A glob scope (the noun): ``include`` minus ``exclude``, re-added by ``override``."""

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    override: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckpointBinding:
    """Maps a scope to the action ids a matching changed file owes."""

    scope: CheckpointScope
    actions: tuple[str, ...]


@dataclass(frozen=True)
class CheckpointModel:
    """The effective checkpoint declaration: an action registry plus bindings."""

    actions: dict[str, CheckpointAction]
    bindings: tuple[CheckpointBinding, ...]


CHECKPOINT_COMMIT_EVIDENCE = ["telec code commit"]
# A post-commit review is satisfied once the commit(s) are dispatched to a
# reviewer — either a fresh run of /next-review-commits or a remediation sent to
# an already-open reviewer ("review commits <sha>" via telec sessions send).
CHECKPOINT_REVIEW_DISPATCH_EVIDENCE = ["/next-review-commits", "review commits"]

# Universal base actions (the verbs). TeleClaude owns this registry; every
# onboarded project inherits it and references these ids in its own bindings or
# extends it with project-specific actions. `log-check` carries the {slug}
# placeholder (filled from ProjectConfig.project_slug) and the {window}
# placeholder (filled at surface time from elapsed turn duration).
CHECKPOINT_BASE_ACTIONS: dict[str, CheckpointAction] = {
    "install": CheckpointAction(
        id="install",
        run="Run `make install`",
        evidence=("make install",),
        main_only=True,
        precedence=10,
    ),
    "reload-self": CheckpointAction(
        id="reload-self",
        run="Reload artifacts: `telec sessions restart self`",
        evidence=("telec sessions restart self",),
        precedence=50,
    ),
    "sync": CheckpointAction(
        id="sync",
        run="Run `telec sync`",
        evidence=("telec sync",),
        main_only=True,
        precedence=55,
    ),
    "log-check": CheckpointAction(
        id="log-check",
        run="Check logs: `instrukt-ai-logs {slug} --since {window} --exclude git-wrapper`",
        evidence=("instrukt-ai-logs",),
        precedence=58,
    ),
    "test": CheckpointAction(
        id="test",
        run="Run targeted tests for only YOUR changed behavior",
        evidence=("pytest", "make test", "telec code test"),
        precedence=60,
    ),
}

# Universal base bindings (telec-contract paths). They fire on every checkpoint
# in every onboarded project regardless of language. `test` and `log-check` are
# NOT bound here — they attach to a project-declared `code` scope (code is an
# allowlist; an unmatched file is silent).
CHECKPOINT_BASE_DOCS_BINDING = CheckpointBinding(scope=CheckpointScope(include=("docs/**",)), actions=("sync",))
CHECKPOINT_BASE_AGENTS_BINDING = CheckpointBinding(
    scope=CheckpointScope(include=("agents/**", ".agents/**", "**/AGENTS.master.md")),
    actions=("sync", "reload-self"),
)
CHECKPOINT_BASE_CODE_BINDING = CheckpointBinding(
    scope=CheckpointScope(include=("Makefile", ".pre-commit-config.yaml", ".gitattributes", ".husky/pre-commit")),
    actions=("install",),
)
# Worktree directory name (git worktrees live at {project}/trees/{slug})
WORKTREE_DIR = "trees"

# Misc markers / defaults
RELATIVE_CURRENT = "."
TC_WORKDIR = "TC WORKDIR"
DB_IN_MEMORY = ":memory:"

# Fallback labels
LABEL_TOOL = "tool"

# Markdown tokens
MARKDOWN_FENCE = "```"
MARKDOWN_INLINE_CODE = "`"


# Cache/event names
class CacheEvent(str, Enum):
    SESSION_STARTED = "session_started"
    SESSION_UPDATED = "session_updated"
    SESSION_CLOSED = "session_closed"
    PROJECTS_SNAPSHOT = "projects_snapshot"
    TODOS_SNAPSHOT = "todos_snapshot"
    PROJECTS_INITIAL = "projects_initial"
    PREPARATION_INITIAL = "preparation_initial"
    COMPUTER_UPDATED = "computer_updated"
    PROJECTS_UPDATED = "projects_updated"
    PROJECT_UPDATED = "project_updated"
    TODOS_UPDATED = "todos_updated"
    TODO_CREATED = "todo_created"
    TODO_UPDATED = "todo_updated"
    TODO_RENAMED = "todo_renamed"
    TODO_REMOVED = "todo_removed"


# Cache key separator
CACHE_KEY_SEPARATOR = ":"

# Cache data types
DATA_TYPE_SESSIONS = "sessions"
DATA_TYPE_TODOS = "todos"
DATA_TYPE_PROJECTS = "projects"
DATA_TYPE_PREPARATION = "preparation"


# WebSocket subscription keys
class WsAction(str, Enum):
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"


class AdapterKey(str, Enum):
    API = "api"


class AdapterOp(str, Enum):
    DELETE_MESSAGE = "delete_message"


class UiScope(str, Enum):
    ALL = "all_ui"


# Redis internal settings
REDIS_MAX_CONNECTIONS = 50
REDIS_SOCKET_TIMEOUT = 60  # Increased to accommodate poor network conditions
REDIS_POOL_TIMEOUT: float = 30.0  # Max seconds to wait for a pooled connection before erroring
REDIS_MESSAGE_STREAM_MAXLEN = 10000  # Max messages to keep per computer
REDIS_OUTPUT_STREAM_MAXLEN = 10000  # Max output messages per session
REDIS_OUTPUT_STREAM_TTL = 3600  # Auto-expire output streams after 1 hour
REDIS_REFRESH_COOLDOWN_SECONDS = 30  # Minimum time between remote refreshes per peer+data type

# Directories mounted into restricted (sandboxed) agent profiles.
# Add paths here to make them accessible to all agents in restricted mode.
_LOG_STATE_ROOT = f"{os.environ.get('XDG_STATE_HOME') or os.path.expanduser('~/.local/state')}/instrukt-ai"
RESTRICTED_MOUNT_DIRS: tuple[str, ...] = (
    "~/.teleclaude/docs",
    _LOG_STATE_ROOT,
)

# Agent-specific formatters for restricted mount dirs.
_CLAUDE_MOUNT = " ".join(f"--add-dir {d}" for d in RESTRICTED_MOUNT_DIRS)
_GEMINI_MOUNT = ",".join(RESTRICTED_MOUNT_DIRS)
_CODEX_MOUNT = " ".join(f"--add-dir {d}" for d in RESTRICTED_MOUNT_DIRS)

# Git `--author` identity per agent (NOT user-configurable).
# These are the vendors' own global GitHub App bot accounts: public, stable, and
# identical for every installation. GitHub attributes a commit by exact email
# match, so the numeric-id form is what links the commit to the bot account.
GIT_AUTHOR_IDENTITIES: dict[str, str] = {
    "claude": "claude[bot] <209825114+claude[bot]@users.noreply.github.com>",
    "codex": ("chatgpt-codex-connector[bot] <199175422+chatgpt-codex-connector[bot]@users.noreply.github.com>"),
    "gemini": "gemini-cli[bot] <218312386+gemini-cli[bot]@users.noreply.github.com>",
}

# Agent protocol (NOT user-configurable)
# Fixed interface contracts for each agent CLI binary.
# The only user-configurable field is `binary` in config.yml (wrapper path).
AgentProtocolDict = dict[str, str | dict[str, str]]
AGENT_PROTOCOL: dict[str, AgentProtocolDict] = {
    "claude": {
        "session_dir": "~/.claude/sessions",
        "log_pattern": "*.jsonl",
        "session_root": "~/.claude/projects",
        "session_pattern": "*/*.jsonl",
        "profiles": {
            "default": ('--dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\''),
            "restricted": (
                "--strict-mcp-config"
                f' --settings \'{{"forceLoginMethod": "claudeai", "enabledMcpjsonServers": []}}\''
                f" {_CLAUDE_MOUNT}"
            ),
        },
        "model_flags": {
            "fast": "--model 'claude-sonnet-5[1m]' --effort low",
            "med": "--model 'claude-sonnet-5[1m]' --effort high",
            "slow": "--model 'claude-fable-5[1m]' --effort high",
            "default": "",
        },
        "exec_subcommand": "",
        "interactive_flag": "",
        "non_interactive_flag": "-p",
        "resume_template": "{base_cmd} --resume {session_id}",
        "continue_template": "{base_cmd} --continue",
    },
    "gemini": {
        "session_dir": "~/.gemini/antigravity-cli/brain",
        "log_pattern": "*/.system_generated/logs/transcript.jsonl",
        "session_root": "~/.gemini/antigravity-cli/brain",
        "session_pattern": "*/.system_generated/logs/transcript.jsonl",
        "profiles": {
            "default": "--dangerously-skip-permissions",
            "restricted": f"--sandbox --add-dir {_GEMINI_MOUNT}",
        },
        "model_flags": {
            "fast": "--model 'Gemini 3.6 Flash (Low)'",
            "med": "--model 'Gemini 3.6 Flash (Medium)'",
            "slow": "--model 'Gemini 3.6 Flash (High)'",
            "default": "",
        },
        "exec_subcommand": "",
        "interactive_flag": "-i",
        "non_interactive_flag": "-p",
        "resume_template": "{base_cmd} --conversation {session_id}",
        "continue_template": "{base_cmd} --continue",
    },
    "codex": {
        "session_dir": "~/.codex/sessions",
        "log_pattern": "*.jsonl",
        "session_root": "~/.codex/sessions",
        "session_pattern": "**/*.jsonl",
        "profiles": {
            "default": "--dangerously-bypass-approvals-and-sandbox --search",
            "restricted": f"--full-auto --search {_CODEX_MOUNT}",
        },
        "model_flags": {
            "fast": ("-m gpt-5.6-luna --config model_reasoning_effort='medium'"),
            "med": ("-m gpt-5.6-terra --config model_reasoning_effort='high'"),
            "slow": ("-m gpt-5.6-sol --config model_reasoning_effort='high'"),
            "default": "",
        },
        "exec_subcommand": "exec",
        "interactive_flag": "",
        "non_interactive_flag": "",
        "resume_template": "{base_cmd} resume {session_id}",
        "continue_template": "{base_cmd} resume --last",
    },
}
