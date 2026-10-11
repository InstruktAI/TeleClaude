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


# System roles
class SystemRole(StrEnum):
    """Closed vocabulary for roles a session can carry."""

    SYSTEM = "system"
    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"
    INTEGRATOR = "integrator"
    TASKER = "tasker"
    COORDINATOR = "coordinator"
    JOB_RUNNER = "job_runner"


ROLE_SYSTEM = SystemRole.SYSTEM
ROLE_ORCHESTRATOR = SystemRole.ORCHESTRATOR
ROLE_WORKER = SystemRole.WORKER
ROLE_INTEGRATOR = SystemRole.INTEGRATOR
ROLE_TASKER = SystemRole.TASKER
SYSTEM_DAEMON_PRINCIPAL = "system:daemon"
# A job-runner session is a recurring scheduled job, e.g. log_bug_hunter or a
# generic cron agent job. It is one of the standing roles (see
# STANDING_SYSTEM_ROLES / is_standing_role below) permitted a no-human lineage
# root at todo/bug creation — see local/projects/teleclaude/spec/domain/workflow.
ROLE_JOB_RUNNER = SystemRole.JOB_RUNNER


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

    COMMAND = "command"
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


class SlashCommand(StrEnum):
    """Canonical slash commands dispatched to agent sessions.

    Values are domain-qualified (``<domain>/<name>``), matching the
    partitioned global corpus each names — see
    ``teleclaude.agent_artifacts`` and ``local/projects/teleclaude/design/architecture/agent-artifact-distribution#corpus-layout-and-names``.
    """

    BUILD = "sdlc/build"
    REVIEW_BUILD = "sdlc/review-build"
    REVIEW_PRD = "sdlc/review-prd"
    REVIEW_PLAN = "sdlc/review-plan"
    REVIEW_ARCHITECTURE = "sdlc/review-architecture"
    REVIEW_COMMITS = "sdlc/review-commits"
    FINALIZE = "sdlc/finalize"
    PREPARE_INTAKE = "sdlc/prepare-intake"
    PREPARE_ARCHITECTURE = "sdlc/prepare-architecture"
    PREPARE_DIAGNOSE = "sdlc/prepare-diagnose"
    PREPARE_PLAN = "sdlc/prepare-plan"
    PREPARE_TASK = "sdlc/prepare-task"
    DRIFT_ANALYZE = "sdlc/drift-analyze"
    PREPARE = "sdlc/prepare"
    WORK = "sdlc/work"
    RUN_TASK = "sdlc/run-task"
    INTEGRATE = "sdlc/integrate"
    COORDINATE = "sdlc/coordinate"
    CREATE = "creative/create"
    CREATE_ART = "creative/create-art"
    CREATE_HTML = "creative/create-html"
    DEFER = "sdlc/defer"
    RUN_JOB = "general/run-job"
    ACTIVATE_PROCEDURE = "general/activate-procedure"


# Canonical lifecycle commands that may run without a todo slug: the prepare
# orchestrator, create orchestrator, and integrator can select work
# themselves, review-commits is bound to commit SHAs rather than a slug, and
# the coordinator watches the fleet without any todo at all. The dispatch
# required-slug gate at both create doors reads this single set so they
# cannot disagree on which commands may run argless.
NON_SLUG_BOUND_COMMANDS = frozenset(
    {
        SlashCommand.PREPARE,
        SlashCommand.INTEGRATE,
        SlashCommand.REVIEW_COMMITS,
        SlashCommand.COORDINATE,
        SlashCommand.RUN_JOB,
        SlashCommand.CREATE,
        SlashCommand.ACTIVATE_PROCEDURE,
    }
)


class JobRole(str, Enum):
    """Canonical job roles for sessions spawned by slash commands."""

    BUILDER = "builder"
    COORDINATOR = "coordinator"
    REVIEWER = "reviewer"
    FINALIZER = "finalizer"
    INTAKER = "intaker"
    PLANNER = "planner"
    DIAGNOSER = "diagnoser"
    ARCHITECT = "architect"
    TASK_PREPARER = "task-preparer"
    TASK_RUNNER = "task-runner"
    DRIFT_ANALYZER = "drift-analyzer"
    PREPARE_ORCHESTRATOR = "prepare-orchestrator"
    WORK_ORCHESTRATOR = "work-orchestrator"
    CREATE_ORCHESTRATOR = "create-orchestrator"
    ARTIST = "artist"
    FRONTENDER = "frontender"
    INTEGRATOR = "integrator"
    JOB_RUNNER = "job-runner"
    PROCEDURE_AGENT = "procedure-agent"


# Maps slash commands to the (system_role, job_role) a session running that command holds.
# Used both by run_slash_command() internally and exported for api_server.py.
#
# Most prepare drafting phases (intake, architecture, plan) are loaded inline by the
# prepare orchestrator itself — `_load_procedure`, never `_dispatch_worker` — so the
# session running them IS the orchestrator, and they carry ROLE_ORCHESTRATOR because the
# role a command confers must match the session that actually runs it. Diagnose is the
# named exception: it is dispatched to a cross-model peer, so the session running it is a
# worker for fleet classification, while its job still names what it authors.
# The prepare-author write predicate (`PREPARE_AUTHOR_JOB_ROLES`) recognizes
# the job regardless of which system role carries it.
COMMAND_ROLE_MAP: dict[SlashCommand, tuple[SystemRole, JobRole]] = {
    SlashCommand.BUILD: (ROLE_WORKER, JobRole.BUILDER),
    SlashCommand.REVIEW_BUILD: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.REVIEW_PRD: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.REVIEW_PLAN: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.REVIEW_ARCHITECTURE: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.REVIEW_COMMITS: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.CREATE_ART: (ROLE_WORKER, JobRole.ARTIST),
    SlashCommand.CREATE_HTML: (ROLE_WORKER, JobRole.FRONTENDER),
    SlashCommand.FINALIZE: (ROLE_WORKER, JobRole.FINALIZER),
    SlashCommand.PREPARE_INTAKE: (ROLE_ORCHESTRATOR, JobRole.INTAKER),
    SlashCommand.PREPARE_ARCHITECTURE: (ROLE_ORCHESTRATOR, JobRole.ARCHITECT),
    SlashCommand.PREPARE_DIAGNOSE: (ROLE_WORKER, JobRole.DIAGNOSER),
    SlashCommand.PREPARE_PLAN: (ROLE_ORCHESTRATOR, JobRole.PLANNER),
    SlashCommand.PREPARE_TASK: (ROLE_TASKER, JobRole.TASK_PREPARER),
    SlashCommand.DRIFT_ANALYZE: (ROLE_WORKER, JobRole.DRIFT_ANALYZER),
    SlashCommand.PREPARE: (ROLE_ORCHESTRATOR, JobRole.PREPARE_ORCHESTRATOR),
    SlashCommand.WORK: (ROLE_ORCHESTRATOR, JobRole.WORK_ORCHESTRATOR),
    SlashCommand.RUN_TASK: (ROLE_TASKER, JobRole.TASK_RUNNER),
    SlashCommand.INTEGRATE: (ROLE_INTEGRATOR, JobRole.INTEGRATOR),
    SlashCommand.COORDINATE: (SystemRole.COORDINATOR, JobRole.COORDINATOR),
    SlashCommand.CREATE: (ROLE_ORCHESTRATOR, JobRole.CREATE_ORCHESTRATOR),
    SlashCommand.RUN_JOB: (ROLE_JOB_RUNNER, JobRole.JOB_RUNNER),
    SlashCommand.ACTIVATE_PROCEDURE: (ROLE_TASKER, JobRole.PROCEDURE_AGENT),
}

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

# Lifecycle build/finalize jobs are the todo-worktree source writers. The
# checkpoint matches the job and worktree slug before selecting their dirty set.
TODO_WORKTREE_WRITER_JOB_ROLES: frozenset[str] = frozenset(
    {
        JobRole.BUILDER.value,
        JobRole.FINALIZER.value,
    }
)

# The jobs that belong to the work lane: the work orchestrator and its worktree
# writers. `reviewer` and `drift-analyzer` are dispatched by both lanes, so no
# job places them in either one.
WORK_LANE_JOB_ROLES: frozenset[str] = frozenset({JobRole.WORK_ORCHESTRATOR.value, *TODO_WORKTREE_WRITER_JOB_ROLES})

# Standing roles carry no commanding session, whatever door created them. The
# integrator and the coordinator are identified by the session's `job` field;
# the job runner is identified by `system_role`, because its own command
# argument displaces the mapped `job` value before it reaches
# COMMAND_ROLE_MAP. Neither field alone resolves all three — see
# local/projects/teleclaude/spec/feature/agent_runtime/session-authority.
STANDING_JOB_ROLES: frozenset[str] = frozenset(
    {
        JobRole.INTEGRATOR.value,
        JobRole.COORDINATOR.value,
    }
)
STANDING_SYSTEM_ROLES: frozenset[str] = frozenset({ROLE_JOB_RUNNER})


def is_standing_role(system_role: str | None, job: str | None) -> bool:
    """Answer whether a session's persisted ``(system_role, job)`` pair is a standing role.

    Reads both fields because neither alone resolves all three standing
    roles: ``job`` is authoritative for the integrator and the coordinator,
    ``system_role`` for the job runner.
    """
    return job in STANDING_JOB_ROLES or system_role in STANDING_SYSTEM_ROLES


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
    for a deferred action.
    """

    id: str
    command: tuple[str, ...]
    main_only: bool = False
    precedence: int = 0
    on_demand: OnDemandDisposition = OnDemandDisposition.RUN
    owed_probe: tuple[str, ...] | None = None


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


CHECKPOINT_COMMIT_EVIDENCE = ["telec code commit"]
# A fresh run of review-commits (with an optional leading slash, qualified or
# bare) dispatches a post-commit review. A send to an already-open reviewer is
# recognized by its target session, not by text (see the checkpoint evidence).
CHECKPOINT_REVIEW_DISPATCH_EVIDENCE = [SlashCommand.REVIEW_COMMITS.value]

# Review-routing text shared by every surface that routes a commit on main to
# review (the commit card, the checkpoint's post-commit prompt, the prepare
# machine's PREPARED hold). The authoring session decides per commit; the
# surfaces only name candidates and carry this test.
COMMIT_REVIEW_INTENT_TEST = (
    "Decide by what each commit set out to do: a commit through which you wrote new or changed code "
    "or documentation content owes an independent reviewer; a commit through which you wrote neither "
    "(a removal, a merge of work already reviewed where it was written, a validation or other "
    "mechanical repair) owes none."
)
COMMIT_REVIEW_DISCARD_COMMAND_TEMPLATE = "telec code stamp {sha} --verdict approve --reason <text>"
COMMIT_REVIEW_DISCARD_PLACEHOLDER = "<sha>"

# Universal base judgment actions (the verbs). TeleClaude owns this registry; every
# onboarded project inherits it and references these ids in its own bindings or
# extends it with project-specific actions. `log-check` carries the {slug}
# placeholder (filled from ProjectConfig.project_slug) and the {window}
# placeholder (filled at surface time from elapsed turn duration).
CHECKPOINT_BASE_ACTIONS: dict[str, CheckpointAction] = {
    LOG_CHECK_ACTION_ID: CheckpointAction(
        id=LOG_CHECK_ACTION_ID,
        run="Check logs: `instrukt-ai-logs {slug} --since {window} --exclude git-wrapper`",
        evidence=("instrukt-ai-logs",),
        main_only=True,
        off_main_eligible=False,
        precedence=58,
    ),
    "test": CheckpointAction(
        id="test",
        run="Run targeted tests for only YOUR changed behavior",
        evidence=("pytest", "make test", "telec code test"),
        precedence=60,
    ),
}


BLUEPRINT_MAINTENANCE_ACTION_ID: Final[str] = "blueprint"


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
