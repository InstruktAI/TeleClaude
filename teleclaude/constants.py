"""Constants used across TeleClaude.
This module defines shared constants to ensure consistency.
"""

import functools
import re
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum, StrEnum
from typing import Final

from teleclaude import agent_registry
from teleclaude.core.worktree_layout import WORKTREE_DIR as WORKTREE_DIR
from teleclaude.events.type_pattern import TypePattern

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
CODEX_HOOK_STOP_TIMEOUT_SEC: Final[int] = 30
VOICE_TRANSCRIPTION_TIMEOUT_S = 120.0
AUDIO_STT_FETCH_TIMEOUT_S = 60.0
AUDIO_STT_INSPECTION_TIMEOUT_S = 10.0
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
WHATSAPP_API_VERSION = "v21.0"
UI_MESSAGE_MAX_CHARS = 3900  # Char budget for content selection (format + fit)
TELEGRAM_MAX_MESSAGE_BYTES = 4096  # Telegram API hard limit for message text

# Common protocol tokens (internal canonical strings)
MAIN_MODULE = "__main__"
LOCAL_COMPUTER = "local"
ENV_ENABLE = "1"
TUI_SESSION_ENV_KEY = "TELEC_TUI_SESSION"
INTEGRATOR_GITOP_ENV = "TELECLAUDE_INTEGRATOR_GITOP"
# Marker prefixing a manual lifecycle operation's result text when the runner
# was not dispatched (skipped, invalid kind, or a claim conflict). A completed
# operation carrying this marker is a refusal, not a success.
RUNNER_NOT_DISPATCHED = "RUNNER_NOT_DISPATCHED"


class SessionTarget(StrEnum):
    """Names a session reference may take in place of a session id."""

    SELF = "self"


SYSTEM_DAEMON_PRINCIPAL = "system:daemon"

# The branch a project's revisions are admitted on: CI outcomes of this branch decide a revision's green.
MAIN_BRANCH = "main"


class DriverLaunchClass(StrEnum):
    """How a session-create launch is treated by the driver-start dedup guard.

    A create door always writes a new session row, so the guard keys on what the
    requested launch IS — classified from its slash command:

    - ``ORCHESTRATOR``: a lifecycle orchestrator driver (``sdlc/prepare``,
      ``sdlc/work``). Refused against ANY live holder, caller-independent — a
      second orchestrator row for a driven slug is never legitimate.
    - ``TASK_LANE``: the task-lane driver (``sdlc/run-task``). Refused against a
      live ``active_runner`` for the slug.
    - ``REVIEWER``: a reviewer worker (``sdlc/review-build``,
      ``sdlc/review-plan``, ``sdlc/review-architecture``,
      ``sdlc/review-commits``). Refused against a live reviewer already open
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
HUMAN_ROLE_CUSTOMER = "customer"
HUMAN_ROLES = (HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CUSTOMER)

# The CLI-facing error surface recognizes this login-required detail and names
# the fix without string-matching arbitrary server text.
LOGIN_REQUIRED_DETAIL = "login required in multi-user mode"

# The wire kind of a draining daemon's refusal. The daemon's HTTP and relay
# refusals produce it and the CLI recognizes it, so neither side spells it twice.
SHUTDOWN_REFUSAL_KIND = "shutdown_refusal"

SNIPPET_VISIBILITY_PUBLIC = "public"
SNIPPET_VISIBILITY_INTERNAL = "internal"
SNIPPET_VISIBILITY_VALUES = (SNIPPET_VISIBILITY_PUBLIC, SNIPPET_VISIBILITY_INTERNAL)


class ArtifactKind(StrEnum):
    """Agent-artifact kinds the transpiler emits and the validator grades."""

    SKILL = "skill"


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
    # A row whose first grouped child transitioned it out of the todo
    # lifecycle for good. Never dispatched, held, delivered, or removed;
    # renders only as context wherever its children render.
    HOLDER = "holder"


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


class HeadlessBootstrapField(StrEnum):
    """Receiver-owned fields carried between hook ingress and the outbox."""

    AUTHORIZATION = "headless_bootstrap"
    CALLER_EMAIL = "headless_bootstrap_caller_email"


class MarkerState(StrEnum):
    """Represent whether the inherited session-identity marker is usable."""

    ABSENT = "absent"
    INVALID = "invalid"
    VALID = "valid"


# How long terminal runtime records (inbound queue rows, finished operations, hook outbox rows) stay after their
# creation. The inbound queue's source-identity dedupe, and so everything that relies on it, reaches back this far.
RUNTIME_RECORD_RETENTION_WINDOW = timedelta(days=7)

# Canonical "slug not found" wording, shared by every daemon-API and CLI
# surface that reports a slug absent from the resolved todos.db.
SLUG_NOT_FOUND_DETAIL = "slug '{slug}' not found in todo list"
REMOVED_TODO_RETENTION_WINDOW = timedelta(days=7)
REMOVED_TODO_MUTATION_REFUSED_DETAIL = (
    "todo '{slug}' is removed and retained for {retention_days} days; "
    "locate its durable id with `telec todo show {slug} --include-removed`, then recover with "
    "`telec todo reactivate --id <row-id>`"
)

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
# kept lean. The run agent appends dated entries per firing; the firing-start
# stamp appends one timed firing line per firing. A run-phase product — not
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
# A failed-check bug's record of its failures, occurrences and recoveries. The platform's failed-check filer is
# its only writer; it is read-only to every other caller and, like "log", not prepare-owned, not drift-tracked
# and not lifecycle-relevant.
ARTIFACT_CHECK_FAILURES = "check-failures"


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
        ARTIFACT_CHECK_FAILURES,
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

# Kinds only the platform writes: callers may read them and may not write or remove them.
ARTIFACT_NAMES_PLATFORM_WRITTEN: frozenset[str] = frozenset({ARTIFACT_CHECK_FAILURES})
ARTIFACT_PLATFORM_WRITTEN_REFUSAL = "artifact kind '{name}' is platform-owned read-only: only the platform writes it"

ARTIFACT_NAMES_WRITABLE: frozenset[str] = ARTIFACT_NAMES - ARTIFACT_NAMES_RETIRED - ARTIFACT_NAMES_PLATFORM_WRITTEN

# The prepare-owned derivation-root artifacts. Writable only by a prepare-phase
# writer (a prepare-orchestrator, human-identity session, or roleless operator
# session); writes are versioned and independent of lifecycle ownership. See the Write authority contract in
# docs/local/spec/feature/workflow/artifact-versioning.md.
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


class JudgmentOwner(StrEnum):
    """The role responsible for completing a checkpoint judgment."""

    SESSION = "session"
    INTEGRATOR = "integrator"


LOG_CHECK_ACTION_ID = "log-check"


@dataclass(frozen=True)
class CheckpointAction:
    """A judgment action in the checkpoint registry (the verb).

    Evidence, gating, and surface order live on the action, never on a binding
    — so many bindings may trigger one action while its suppression,
    branch-gating, and surface order are defined exactly once. ``run`` and
    ``evidence`` may carry the ``{slug}`` placeholder, filled from the project's
    ``project_slug`` when the effective model is loaded; ``run`` may carry the
    ``{window}`` placeholder, filled with the elapsed-time log window at surface.
    """

    id: str
    run: str
    evidence: tuple[str, ...] = ()
    main_only: bool = False
    off_main_eligible: bool = True
    precedence: int = 0
    evidence_must_follow_last_mutation: bool = False
    judged_by: JudgmentOwner = JudgmentOwner.SESSION

    def effective_evidence(self) -> tuple[str, ...]:
        """Evidence substrings proving the action ran; defaults to ``[run]``."""
        return self.evidence if self.evidence else (self.run,)


class OnDemandDisposition(StrEnum):
    """What an on-demand run does with a maintenance action."""

    RUN = "run"
    DEFER = "defer"


@dataclass(frozen=True)
class MaintenanceAction:
    """A deterministic action performed at the canonical-main boundary.

    ``on_demand`` tells a manual run whether to perform the action or only report
    whether it is owed; ``owed_probe`` is the command that answers that question
    for a deferred action. ``runs_while_serving`` declares whether it is safe to
    run while the daemon serves.
    """

    id: str
    command: tuple[str, ...]
    main_only: bool = False
    precedence: int = 0
    on_demand: OnDemandDisposition = OnDemandDisposition.RUN
    owed_probe: tuple[str, ...] | None = None
    runs_while_serving: bool = False


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
class CheckpointEventBinding:
    """Maps event type patterns to the maintenance action ids an event of a selected type owes."""

    patterns: tuple[TypePattern, ...]
    actions: tuple[str, ...]

    def selects(self, event_type: str) -> bool:
        """Whether any of the binding's patterns selects the event type."""
        return any(pattern.matches(event_type) for pattern in self.patterns)


class CheckpointActivation(StrEnum):
    """Closed activation events that can select main-only maintenance."""

    CANONICAL_MAIN = "canonical_main"


@dataclass(frozen=True)
class CheckpointActivationBinding:
    """Maps one canonical-main activation to the maintenance action ids it owes."""

    activation: CheckpointActivation
    actions: tuple[str, ...]


@dataclass(frozen=True)
class CheckpointModel:
    """The effective checkpoint and maintenance registries plus shared bindings.

    ``bindings`` are selected by changed paths, ``event_bindings`` by event type, and
    ``activation_bindings`` by a canonical-main activation.
    """

    actions: dict[str, CheckpointAction]
    maintenance: dict[str, MaintenanceAction]
    bindings: tuple[CheckpointBinding, ...]
    event_bindings: tuple[CheckpointEventBinding, ...] = ()
    activation_bindings: tuple[CheckpointActivationBinding, ...] = ()


CHECKPOINT_TEST_EVIDENCE_COMMAND = "telec repo test"
CHECKPOINT_COMMIT_EVIDENCE_COMMAND = "telec repo commit"
CHECKPOINT_COMMIT_EVIDENCE = [CHECKPOINT_COMMIT_EVIDENCE_COMMAND]
# A fresh run of review-commits (with an optional leading slash, qualified or
# bare) dispatches a post-commit review. A send to an already-open reviewer is
# recognized by its target session, not by text (see the checkpoint evidence).
CHECKPOINT_REVIEW_DISPATCH_EVIDENCE = ["sdlc/procedure/lifecycle/work/review-commits"]

# Review-routing text shared by every surface that routes a commit on main to
# review (the commit card, the checkpoint's post-commit prompt, the prepare
# machine's PREPARED hold). The authoring session decides per commit; the
# surfaces only name candidates and carry this test.
COMMIT_REVIEW_INTENT_TEST = (
    "Decide by what a wrong change would cost: review is owed when the commit carries a consequence "
    "you cannot establish alone — new or changed logic, a state or data shape, a contract between "
    "components, concurrency, security, or what a snippet or agent artifact directs agents to do. "
    "Every other commit you stamp yourself, without asking anyone: a removal, a merge of work already "
    "reviewed where it was written, a validation or mechanical repair, a rename or move, formatting, "
    "and wording or prompt prose whose effect is presentation, including wording a human shaped with you."
)
COMMIT_REVIEW_DISCARD_COMMAND_TEMPLATE = "telec repo stamp {sha} --verdict approve --reason <text>"
COMMIT_REVIEW_DISCARD_PLACEHOLDER = "<sha>"

# Universal base judgment actions (the verbs). TeleClaude owns this registry; every
# onboarded project inherits it and references these ids in its own bindings or
# extends it with project-specific actions. `log-check` carries the {slug}
# placeholder (filled from ProjectConfig.project_slug) and the {window}
# placeholder (filled at surface time from elapsed turn duration).
CHECKPOINT_BASE_ACTIONS: dict[str, CheckpointAction] = {
    LOG_CHECK_ACTION_ID: CheckpointAction(
        id=LOG_CHECK_ACTION_ID,
        run="Check logs: `instrukt-ai-logs {slug} --since {window}`",
        evidence=("instrukt-ai-logs",),
        main_only=True,
        off_main_eligible=False,
        precedence=58,
    ),
    "test": CheckpointAction(
        id="test",
        run="Run targeted tests for only YOUR changed behavior",
        evidence=("pytest", "make test", CHECKPOINT_TEST_EVIDENCE_COMMAND),
        precedence=60,
    ),
}


BLUEPRINT_MAINTENANCE_ACTION_ID: Final[str] = "blueprint"
RESTART_MAINTENANCE_ACTION_ID: Final[str] = "restart"


CHECKPOINT_BASE_MAINTENANCE: dict[str, MaintenanceAction] = {
    "install": MaintenanceAction(
        id="install",
        command=("{interpreter}", "-m", "teleclaude.core.integration.install_action"),
        main_only=True,
        precedence=10,
    ),
    "plumbing-convergence": MaintenanceAction(
        id="plumbing-convergence",
        command=("{interpreter}", "-m", "teleclaude.project_setup.plumbing", "."),
        main_only=True,
        precedence=15,
    ),
    "sync": MaintenanceAction(
        id="sync",
        command=(
            "{interpreter}",
            "-m",
            "teleclaude.core.integration.publish_action",
            "--after-sha",
            "{after_sha}",
            "--before-sha",
            "{before_sha}",
            "--home",
            "{home}",
        ),
        main_only=True,
        precedence=55,
        runs_while_serving=True,
    ),
    BLUEPRINT_MAINTENANCE_ACTION_ID: MaintenanceAction(
        id=BLUEPRINT_MAINTENANCE_ACTION_ID,
        command=(
            "{interpreter}",
            "-m",
            "teleclaude.core.blueprint.maintenance",
            "--trigger-revision",
            "{after_sha}",
        ),
        main_only=True,
        precedence=50,
        runs_while_serving=True,
    ),
}

# The only two locations an agent-artifact source ever lives: a project's own
# root master, and its `agents/` tree (root masters/addenda, the tiered
# global/project commands and skills). `.agents/` is deliberately excluded — it is the delivery location
# the local phase writes to, never a source. Owned here (rather than in
# `teleclaude.agent_artifacts`, the registry that classifies paths against
# this same set) because `constants` sits below `project_root`/`domains` in
# the import graph and importing the registry here would cycle back through
# it; `teleclaude.project_root` and `teleclaude.agent_artifacts` both import
# this tuple as their single source of truth for "where sources live".
AGENT_ARTIFACT_SOURCE_GLOBS: tuple[str, ...] = ("AGENTS.master.md", "agents/**")

# Universal base bindings preserve their scopes for project overlays. Docs and
# agent-artifact scopes trigger sync, while the toolchain scope triggers install;
# project-declared code scopes attach test and log-check separately.
CHECKPOINT_BASE_DOCS_BINDING = CheckpointBinding(scope=CheckpointScope(include=("docs/**",)), actions=("sync",))
CHECKPOINT_HOME_PUBLICATION_BINDING = CheckpointBinding(
    scope=CheckpointScope(
        include=(
            "people/*/docs/**",
            "companies/*/docs/**",
            "AGENTS.master.md",
            "people/*/AGENTS.master.md",
            "companies/*/AGENTS.master.md",
            "companies/*/help-desk/AGENTS.master.md",
        )
    ),
    actions=("sync",),
)
# A declaration decides which masters convergence seeds, and the publication
# that follows compiles them; a committed desk master owes that publication too.
CHECKPOINT_PROJECT_DESK_BINDING = CheckpointBinding(
    scope=CheckpointScope(include=("teleclaude.yml", "help-desk/AGENTS.master.md")),
    actions=("plumbing-convergence", "sync"),
)
CHECKPOINT_HOME_DECLARATION_BINDING = CheckpointBinding(
    scope=CheckpointScope(include=("teleclaude.yml", "people/*/teleclaude.yml", "companies/*/teleclaude.yml")),
    actions=("plumbing-convergence", "sync"),
)
CHECKPOINT_BASE_AGENTS_BINDING = CheckpointBinding(
    scope=CheckpointScope(include=AGENT_ARTIFACT_SOURCE_GLOBS),
    actions=("sync",),
)
CHECKPOINT_BASE_CODE_BINDING = CheckpointBinding(
    scope=CheckpointScope(include=("Makefile", ".pre-commit-config.yaml", ".gitattributes", ".husky/pre-commit")),
    actions=("install",),
)
CHECKPOINT_BASE_BLUEPRINT_ACTIVATION_BINDING = CheckpointActivationBinding(
    activation=CheckpointActivation.CANONICAL_MAIN,
    actions=(BLUEPRINT_MAINTENANCE_ACTION_ID,),
)
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
# Marks a cache notification that drops cached data as stale, as opposed to one that reports data just stored.
CACHE_INVALIDATION_FIELD = "invalidated"


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
# How long an idle stream reader blocks on Redis before it asks again; a socket timeout must outlast it.
REDIS_STREAM_BLOCK_S: Final = 10
REDIS_POOL_TIMEOUT: float = 30.0  # Max seconds to wait for a pooled connection before erroring
REDIS_MESSAGE_STREAM_MAXLEN = 10000  # Max messages to keep per computer
REDIS_OUTPUT_STREAM_MAXLEN = 10000  # Max output messages per session
REDIS_OUTPUT_STREAM_TTL = 3600  # Auto-expire output streams after 1 hour
REDIS_REFRESH_COOLDOWN_SECONDS = 30  # Minimum time between remote refreshes per peer+data type

# Directories mounted into restricted (sandboxed) agent profiles, and the git
# `--author` identity and launch contract per agent: all owned by the
# canonical agent registry. Re-exported here for existing callers; see
# `teleclaude.agent_registry` for the single source of this data.
RESTRICTED_MOUNT_DIRS: tuple[str, ...] = agent_registry.RESTRICTED_MOUNT_DIRS
GIT_AUTHOR_IDENTITIES: dict[str, str] = {
    name.value: definition.git_identity for name, definition in agent_registry.AGENT_REGISTRY.items()
}
AgentProtocolDict = agent_registry.AgentProtocolDict
AGENT_PROTOCOL: dict[str, AgentProtocolDict] = {
    name.value: definition.protocol for name, definition in agent_registry.AGENT_REGISTRY.items()
}


# A request that starts a session may spend driver admission's whole start budget before the session is created,
# so every caller that starts one waits at least this long. A start carried to another computer gets a deadline
# inside it, so its answer returns before the caller stops waiting.
SESSION_START_TIMEOUT_S: Final = 90.0
SESSION_START_RELAY_DEADLINE_S: Final = 80.0
