"""Give every stored session one catalog role and reduce its job to instance identity.

Sessions recorded before roles were composed in the catalog carry a system role and a job whose combination
named their assignment. The migration reads the recorded values as the runtime that wrote them read them and
maps only the combinations that agree with themselves: a role the catalog names, a system role and job that
are the pair the recorded command conferred or an in-place adoption door wrote, a standing role under its own
pair. Every other combination keeps its recorded values, takes the reserved ``unmapped`` role and is written to
the ledger an operator reads. The role of a job or activation row is the one the entry declaration in force at the
cutover names, read for the canonical checkout of the row's project: the live declaration, or the one pending in
the delivery that ships this migration. Persisted launch intents migrate with the rows; the labels recorded on queued
inputs are occurrence provenance and stay as recorded.

The evidence tables below are frozen copies of the tables the retiring runtime wrote the rows under; the
migration never imports them from the live code, which no longer carries them. The ledger is published before
any row changes, and the rows change in one transaction. See
``local/projects/teleclaude/spec/feature/agent_runtime/session-role-migration``.
"""

import json
import os
from collections import defaultdict
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Final

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.config.jobs import EffectiveJob, load_effective_jobs
from teleclaude.context_selector import entry_declaration_state
from teleclaude.core.project_state import resolve_owning_checkout
from teleclaude.core.roles import Role, RoleName, resolve_role
from teleclaude.paths import REPO_ROOT, STATE_DIR

logger = get_logger(__name__)

UNMAPPED_ROLE: Final = "unmapped"
_LEDGER_ENCODING: Final = "utf-8"
_LEDGER_WRITE_MODE: Final = "w"
_LEDGER_TEMPORARY_SUFFIX: Final = ".tmp"
_LEDGER_PATH: Final = STATE_DIR / "migrations" / "119_session_role.json"
_COMMAND_PREFIX: Final = "/"
_PROCEDURE_ID_MARKER: Final = "/"
_SESSION_COLUMNS_SQL: Final = "SELECT name FROM pragma_table_info('sessions')"
_ADD_ROLE_SQL: Final = "ALTER TABLE sessions ADD COLUMN role TEXT"
_DROP_SYSTEM_ROLE_SQL: Final = "ALTER TABLE sessions DROP COLUMN system_role"
_BEGIN_SQL: Final = "BEGIN"
_SELECT_SESSIONS_SQL: Final = "SELECT session_id, system_role, job, command, project_path, working_slug FROM sessions"
_UPDATE_SESSION_SQL: Final = "UPDATE sessions SET role = ?, job = ?, command = ? WHERE session_id = ?"
_SELECT_HANDOVERS_SQL: Final = "SELECT session_id, launch_intent_json FROM session_startup_handovers"
_UPDATE_HANDOVER_SQL: Final = "UPDATE session_startup_handovers SET launch_intent_json = ? WHERE session_id = ?"
_MIGRATION_COMPLETE_TEMPLATE: Final = (
    "Session role migration complete: %d session(s) migrated, %d unmapped (ledger: %s)"
)
_MIGRATION_NAME: Final = "119_session_role"
_NOT_READY_EVENT: Final = "session_role_migration_not_ready"
_NOT_READY_MESSAGE_TEMPLATE: Final = "the {source} of {location} cannot be read ({reason})"
_NOT_READY_PROCEDURE_TEMPLATE: Final = "the {source} of {procedure_id} for {location} cannot be read ({reason})"
#: The delivery that ships this migration. Its pending entry declarations are what its documentation fold
#: publishes verbatim, so before the fold they are the declarations in force at the cutover.
_SHIPPING_DELIVERY: Final = "procedure-role-capability-composition"
_TABLE_EXISTS_SQL: Final = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
_SYSTEM_ROLE_COLUMN: Final = "system_role"
_ROLE_COLUMN: Final = "role"
_HANDOVER_JOB_ROLE_KEY: Final = "job_role"
_HANDOVERS_TABLE: Final = "session_startup_handovers"


class LegacySystemRole(StrEnum):
    """The ``system_role`` values the retiring runtime wrote."""

    WORKER = "worker"
    ORCHESTRATOR = "orchestrator"
    TASKER = "tasker"
    JOB_RUNNER = "job_runner"
    INTEGRATOR = "integrator"
    COORDINATOR = "coordinator"


_STANDING_NAMES: Final = frozenset({RoleName.INTEGRATOR.value, RoleName.COORDINATOR.value})
_RUN_JOB_COMMAND: Final = "general/run-job"
_ACTIVATE_PROCEDURE_COMMAND: Final = "general/activate-procedure"
_INTEGRATE_COMMAND: Final = "sdlc/integrate"
_COORDINATE_COMMAND: Final = "sdlc/coordinate"

_W: Final = LegacySystemRole.WORKER
_O: Final = LegacySystemRole.ORCHESTRATOR
_T: Final = LegacySystemRole.TASKER

#: The ``(system_role, job)`` pair each retired command conferred at launch (the retiring command-role table).
#: The job-runner and activation commands are read by their own rows of the mapping: their ``job`` field held the
#: job name or procedure ID the command argument displaced.
LEGACY_COMMAND_PAIRS: Final[dict[str, tuple[str, str]]] = {
    "sdlc/build": (_W, "builder"),
    "sdlc/review-build": (_W, "reviewer"),
    "sdlc/review-prd": (_W, "reviewer"),
    "sdlc/review-plan": (_W, "reviewer"),
    "sdlc/review-architecture": (_W, "reviewer"),
    "sdlc/review-commits": (_W, "reviewer"),
    "creative/create-art": (_W, "artist"),
    "creative/create-html": (_W, "frontender"),
    "sdlc/finalize": (_W, "finalizer"),
    "sdlc/prepare-intake": (_O, "intaker"),
    "sdlc/prepare-architecture": (_O, "architect"),
    "sdlc/prepare-diagnose": (_W, "diagnoser"),
    "sdlc/prepare-plan": (_O, "planner"),
    "sdlc/prepare-task": (_T, "task-preparer"),
    "sdlc/drift-analyze": (_W, "drift-analyzer"),
    "sdlc/prepare": (_O, "prepare-orchestrator"),
    "sdlc/work": (_O, "work-orchestrator"),
    "sdlc/run-task": (_T, "task-runner"),
    "creative/create": (_O, "create-orchestrator"),
}

#: The pairs an in-place adoption door wrote over whatever command the session had: lane adoption into
#: preparation or work.
ADOPTION_PAIRS: Final = frozenset({(_O, "prepare-orchestrator"), (_O, "work-orchestrator")})

#: The standing pairs the retiring runtime wrote, each with the standing role it names and the one retired command
#: that conferred it. The legacy ``(orchestrator, coordinator)`` pair is the coordinator's earlier representation.
STANDING_PAIRS: Final[dict[tuple[str, str], tuple[RoleName, str]]] = {
    (LegacySystemRole.INTEGRATOR, RoleName.INTEGRATOR.value): (RoleName.INTEGRATOR, _INTEGRATE_COMMAND),
    (LegacySystemRole.COORDINATOR, RoleName.COORDINATOR.value): (RoleName.COORDINATOR, _COORDINATE_COMMAND),
    (LegacySystemRole.ORCHESTRATOR, RoleName.COORDINATOR.value): (RoleName.COORDINATOR, _COORDINATE_COMMAND),
}

#: The retired command each stored ``command`` value names, mapped to the entry procedure its retirement maps it to.
RETIRED_COMMAND_PROCEDURES: Final[dict[str, str]] = {
    "creative/create-art": "creative/procedure/image-generation/nano-banana",
    "creative/create-html": "creative/procedure/visual-drafting",
    "creative/create": "creative/procedure/creative-orchestration",
    "general/author-knowledge": "general/procedure/knowledge-authoring",
    "general/companies-analyze": "general/procedure/company-analysis",
    "general/projects-onboard": "general/procedure/project-onboarding",
    "personal/sweep-email": "personal/procedure/email-triage",
    "sdlc/build": "sdlc/procedure/lifecycle/work/build",
    "sdlc/coordinate": "sdlc/procedure/lifecycle/coordinate",
    "sdlc/defer": "sdlc/procedure/lifecycle/work/deferrals",
    "sdlc/drift-analyze": "sdlc/procedure/lifecycle/prepare/drift-analyze",
    "sdlc/finalize": "sdlc/procedure/lifecycle/work/finalize",
    "sdlc/integrate": "sdlc/procedure/lifecycle/integrate",
    "sdlc/prepare-architecture": "sdlc/procedure/lifecycle/prepare/architecture",
    "sdlc/prepare-diagnose": "sdlc/procedure/lifecycle/prepare/diagnose-peer",
    "sdlc/prepare-intake": "sdlc/procedure/lifecycle/prepare/intake",
    "sdlc/prepare-plan": "sdlc/procedure/lifecycle/prepare/plan-draft",
    "sdlc/prepare-task": "sdlc/procedure/lifecycle/task/prepare-task",
    "sdlc/prepare": "sdlc/procedure/lifecycle/prepare/overview",
    "sdlc/projects-analyze": "sdlc/procedure/project-analysis",
    "sdlc/projects-assess-config": "sdlc/procedure/code-config-assessment",
    "sdlc/research": "sdlc/procedure/research/third-party-research",
    "sdlc/review-architecture": "sdlc/procedure/lifecycle/prepare/review-architecture",
    "sdlc/review-build": "sdlc/procedure/lifecycle/work/review-build",
    "sdlc/review-commits": "sdlc/procedure/lifecycle/work/review-commits",
    "sdlc/review-plan": "sdlc/procedure/lifecycle/prepare/review-plan",
    "sdlc/review-prd": "sdlc/procedure/lifecycle/prepare/review-prd",
    "sdlc/run-task": "sdlc/procedure/lifecycle/task/run-task",
    "sdlc/work": "sdlc/procedure/lifecycle/work/overview",
}


class MappingReason(StrEnum):
    """Why a stored combination could not be mapped to a catalog role."""

    UNNAMED_COMBINATION = "the mapping names no such combination of recorded values"
    JOB_NAMES_NO_CATALOG_ROLE = "the recorded job names no role the catalog keeps"
    RECORDED_VALUES_DISAGREE = "the recorded system role, job and command are not a pair the recorded command conferred or an adoption door wrote"
    PROCEDURE_DECLARES_NO_ROLE = "the procedure the row resolves to declares no role the catalog names"
    JOB_NAMES_NO_DECLARATION = "no configured job carries the recorded job name"
    PROCEDURE_NOT_ONE_JOB = "the recorded procedure is not named by exactly one configured job"
    COMMAND_NAMES_NO_PROCEDURE = "the retired command resolves to no procedure from the row's evidence"


class LedgerKey(StrEnum):
    """The keys of the migration ledger an operator reads."""

    MIGRATED_SESSIONS = "migrated_sessions"
    ROLES = "roles"
    COMBINATIONS = "combinations"
    UNMAPPED = "unmapped"
    SESSION_ID = "session_id"
    SYSTEM_ROLE = "system_role"
    JOB = "job"
    COMMAND = "command"
    WORKING_SLUG = "working_slug"
    HAS_WORKING_SLUG = "has_working_slug"
    REASON = "reason"
    SESSIONS = "sessions"
    RESULT_ROLE = "result_role"
    RESULT_JOB = "result_job"
    RESULT_COMMAND = "result_command"
    DECLARATION = "declaration"
    DECLARATION_SOURCE = "source"
    DECLARATION_PROCEDURE = "procedure_id"
    DECLARATION_JOB = "job_name"
    DECLARATION_STATUS = "declaration_status"


class UnreadableSource(StrEnum):
    """The kinds of source the mapping needs and can find unreadable."""

    OWNING_CHECKOUT = "owning_checkout"
    JOB_CONFIGURATION = "job_configuration"
    ENTRY_DECLARATION = "entry_declaration"


class MigrationNotReady(RuntimeError):
    """A source the mapping needs cannot be read.

    The migration stops before the ledger is published or any row changes; it stays unrecorded and the next
    start runs it again from the same rows. The kind of source, where it was read, the procedure asked about and
    the failure are carried as attributes so the stop is recorded as fields.
    """

    def __init__(
        self, source: UnreadableSource, location: Path, reason: object, procedure_id: str | None = None
    ) -> None:
        self.source = source
        self.location = location
        self.reason = str(reason)
        self.procedure_id = procedure_id
        template = _NOT_READY_MESSAGE_TEMPLATE if procedure_id is None else _NOT_READY_PROCEDURE_TEMPLATE
        super().__init__(
            template.format(source=source.value, location=location, reason=self.reason, procedure_id=procedure_id)
        )


class DeclarationSource(StrEnum):
    """Which evidence established the procedure a scheduled-job or tasker row resolved to."""

    RECORDED_PROCEDURE_ID = "the procedure id recorded on the row"
    CONFIGURED_JOB = "the configured job currently carrying the recorded job name"


class DeclarationStatus(StrEnum):
    """Whether the entry declaration a role was read from was live or pending in the shipping delivery."""

    LIVE = "live"
    PENDING = "pending"


@dataclass(frozen=True)
class DeclaredRole:
    """The catalog role a procedure's declaration in force names, and whether that declaration was live."""

    role: str
    status: DeclarationStatus


@dataclass(frozen=True)
class DeclarationEvidence:
    """The declaration a mapping read: where the procedure came from, the configured job it was resolved against,
    and whether the role's declaration was live or pending."""

    source: DeclarationSource
    procedure_id: str
    job_name: str | None = None
    status: DeclarationStatus | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            LedgerKey.DECLARATION_SOURCE: self.source.value,
            LedgerKey.DECLARATION_PROCEDURE: self.procedure_id,
            LedgerKey.DECLARATION_JOB: self.job_name,
            LedgerKey.DECLARATION_STATUS: self.status.value if self.status is not None else None,
        }


@dataclass(frozen=True)
class SessionRow:
    """The recorded values the mapping reads from one stored session."""

    session_id: str
    system_role: str | None
    job: str | None
    command: str | None
    project_path: str | None
    working_slug: str | None


@dataclass(frozen=True)
class MappedSession:
    """A mappable row's result, or the reason it is unmappable."""

    role: str | None
    job: str | None
    command: str | None
    reason: MappingReason | None = None
    declaration: DeclarationEvidence | None = None


@dataclass(frozen=True)
class CompletedCommand:
    """A row's command mapped through the retirement tables, or the reason the mapping cannot complete."""

    command: str | None
    reason: MappingReason | None = None
    declaration: DeclarationEvidence | None = None


def _normalized_command(command: str | None) -> str | None:
    return command.removeprefix(_COMMAND_PREFIX) if command else None


def _owning_checkout(start: Path) -> Path:
    """The primary checkout that owns the repository containing ``start``, as Workflow publishes the relation.

    A directory under no repository owns itself. A checkout pointer that cannot be read leaves the owner unknown,
    which is not ready: reading the linked worktree itself would map against its branch.
    """
    try:
        owner = resolve_owning_checkout(start)
    except FileNotFoundError as exc:
        raise MigrationNotReady(UnreadableSource.OWNING_CHECKOUT, start, exc) from exc
    return owner if owner is not None else start


class _Declarations:
    """The declaration sources one migration run reads: job configuration and entry declarations.

    Both are read for the canonical checkout of a row's project, never for the linked todo worktree the row was
    recorded in; a row with no project reads the canonical checkout of the repository the runtime runs from, never
    the process's working directory. Each source is read when a mapping first needs it and then reused. A source
    that cannot be read raises ``MigrationNotReady`` — it is never read as declaring nothing. A project whose
    checkout no longer exists carries no job declaration.
    """

    def __init__(self) -> None:
        self._runtime_checkout = _owning_checkout(REPO_ROOT)
        self._jobs: dict[Path, tuple[EffectiveJob, ...]] = {}
        self._roles: dict[tuple[Path, str], DeclaredRole | None] = {}

    def _existing_checkout(self, project_path: str | None) -> Path | None:
        """The canonical checkout of the row's project, or none when the project's checkout no longer exists."""
        if not project_path:
            return self._runtime_checkout
        recorded = Path(project_path)
        if not recorded.is_dir():
            return None
        owner = _owning_checkout(recorded)
        return owner if owner.is_dir() else None

    def jobs(self, project_path: str | None) -> tuple[EffectiveJob, ...]:
        checkout = self._existing_checkout(project_path)
        if checkout is None:
            return ()
        if checkout not in self._jobs:
            try:
                self._jobs[checkout] = load_effective_jobs(checkout)
            except (OSError, ValueError) as exc:
                raise MigrationNotReady(UnreadableSource.JOB_CONFIGURATION, checkout, exc) from exc
        return self._jobs[checkout]

    def role(self, procedure_id: str, project_path: str | None) -> DeclaredRole | None:
        """The role the entry declaration in force at this cutover names, or none when it names no role.

        A live declaration is in force. A declaration pending in the delivery that ships this migration is in
        force too: the code reaches the canonical checkout before that delivery's documentation folds, and the
        migration runs at whichever start comes first. A declaration pending only in another delivery names no role
        at this cutover.
        """
        checkout = self._existing_checkout(project_path) or self._runtime_checkout
        key = (checkout, procedure_id)
        if key not in self._roles:
            self._roles[key] = self._declared_role(procedure_id, checkout)
        return self._roles[key]

    @staticmethod
    def _declared_role(procedure_id: str, checkout: Path) -> DeclaredRole | None:
        state = entry_declaration_state(procedure_id, project_root=checkout)
        if state.unreadable is not None:
            raise MigrationNotReady(
                UnreadableSource.ENTRY_DECLARATION, checkout, state.unreadable, procedure_id=procedure_id
            )
        if state.live.declarations is not None:
            return DeclaredRole(state.live.declarations.role.name.value, DeclarationStatus.LIVE)
        for pending in state.pending:
            if pending.delivered_by == _SHIPPING_DELIVERY and pending.entry.declarations is not None:
                return DeclaredRole(pending.entry.declarations.role.name.value, DeclarationStatus.PENDING)
        return None


def _with_status(evidence: DeclarationEvidence | None, status: DeclarationStatus) -> DeclarationEvidence | None:
    return replace(evidence, status=status) if evidence is not None else None


def _job_procedure(job_name: str, jobs: tuple[EffectiveJob, ...]) -> str | None:
    for job in jobs:
        if job.identity == job_name and job.declaration.job:
            return job.declaration.job.strip()
    return None


def _jobs_naming(procedure_id: str, jobs: tuple[EffectiveJob, ...]) -> list[str]:
    return [job.identity for job in jobs if job.declaration.job and job.declaration.job.strip() == procedure_id]


def _unmapped(row: SessionRow, reason: MappingReason) -> MappedSession:
    return MappedSession(role=UNMAPPED_ROLE, job=row.job, command=row.command, reason=reason)


def _complete_command(
    row: SessionRow, command: str | None, job: str | None, declarations: _Declarations
) -> CompletedCommand:
    """Map the row's command through the retirement tables; a command the evidence cannot complete is a failure.

    ``general/run-job`` resolves to the procedure its row's job names — a procedure ID recorded in ``job`` is
    itself the evidence, a job name resolves through the current declaration carrying it — and
    ``general/activate-procedure`` to the procedure ID recorded in ``job``. Every other command maps through the
    retirement table or stays as recorded.
    """
    if command is None:
        return CompletedCommand(row.command)
    if command == _RUN_JOB_COMMAND:
        if job is None:
            return CompletedCommand(row.command, reason=MappingReason.COMMAND_NAMES_NO_PROCEDURE)
        if _PROCEDURE_ID_MARKER in job:
            return CompletedCommand(job, declaration=DeclarationEvidence(DeclarationSource.RECORDED_PROCEDURE_ID, job))
        procedure_id = _job_procedure(job, declarations.jobs(row.project_path))
        if procedure_id is None:
            return CompletedCommand(row.command, reason=MappingReason.JOB_NAMES_NO_DECLARATION)
        return CompletedCommand(
            procedure_id, declaration=DeclarationEvidence(DeclarationSource.CONFIGURED_JOB, procedure_id, job)
        )
    if command == _ACTIVATE_PROCEDURE_COMMAND:
        if job is None or _PROCEDURE_ID_MARKER not in job:
            return CompletedCommand(row.command, reason=MappingReason.COMMAND_NAMES_NO_PROCEDURE)
        return CompletedCommand(job, declaration=DeclarationEvidence(DeclarationSource.RECORDED_PROCEDURE_ID, job))
    return CompletedCommand(RETIRED_COMMAND_PROCEDURES.get(command, row.command))


def _pair_agrees(system_role: str, job: str, command: str | None) -> bool:
    """Whether ``(system_role, job)`` is the pair the recorded command conferred, or an adoption door's pair."""
    if (system_role, job) in ADOPTION_PAIRS:
        return True
    return command is not None and LEGACY_COMMAND_PAIRS.get(command) == (system_role, job)


def _map_row(row: SessionRow, declarations: _Declarations) -> MappedSession:
    """Map one stored combination through the explicit table; never infer a binding the row does not record.

    The branches run in an order in which none reads a value another branch owns: a ``job_runner`` row is read by
    the job-runner rows of the table whatever its job is called; a row with no system role is roleless only when it
    records no working slug and no coordinator job, and with a working slug it is a worker row with the job it
    records; a standing role is only its own pair; every other row takes its job as its role only when the
    catalog names the job and the pair agrees with the recorded command.
    """
    command = _normalized_command(row.command)
    job = row.job or None
    system_role = row.system_role or None
    if system_role == LegacySystemRole.JOB_RUNNER:
        return _map_job_runner(row, command, job, declarations)

    completed = _complete_command(row, command, job, declarations)
    if completed.reason is not None:
        return _unmapped(row, completed.reason)
    if system_role is None:
        if not row.working_slug and job != RoleName.COORDINATOR:
            return MappedSession(role=None, job=row.job, command=completed.command, declaration=completed.declaration)
        if not row.working_slug:
            return _unmapped(row, MappingReason.UNNAMED_COMBINATION)
        system_role = LegacySystemRole.WORKER

    standing = STANDING_PAIRS.get((system_role, job)) if job else None
    if standing is not None:
        role, own_command = standing
        if command not in (None, own_command):
            return _unmapped(row, MappingReason.RECORDED_VALUES_DISAGREE)
        return MappedSession(role=role.value, job=None, command=completed.command, declaration=completed.declaration)
    if system_role in _STANDING_NAMES or job in _STANDING_NAMES:
        return _unmapped(row, MappingReason.RECORDED_VALUES_DISAGREE)

    if system_role == LegacySystemRole.TASKER and job is not None and _PROCEDURE_ID_MARKER in job:
        return _map_activation(row, command, job, completed, declarations)

    if job is None or not isinstance(resolve_role(job), Role):
        return _unmapped(row, MappingReason.JOB_NAMES_NO_CATALOG_ROLE)
    if not _pair_agrees(system_role, job, command):
        return _unmapped(row, MappingReason.RECORDED_VALUES_DISAGREE)
    return MappedSession(role=job, job=None, command=completed.command, declaration=completed.declaration)


def _map_activation(
    row: SessionRow, command: str | None, job: str, completed: CompletedCommand, declarations: _Declarations
) -> MappedSession:
    """A ``tasker`` row whose job names a procedure: the role that procedure declares, the procedure as its job."""
    if command != _ACTIVATE_PROCEDURE_COMMAND:
        return _unmapped(row, MappingReason.RECORDED_VALUES_DISAGREE)
    declared = declarations.role(job, row.project_path)
    if declared is None:
        return _unmapped(row, MappingReason.PROCEDURE_DECLARES_NO_ROLE)
    return MappedSession(
        role=declared.role,
        job=job,
        command=completed.command,
        declaration=_with_status(completed.declaration, declared.status),
    )


def _map_job_runner(
    row: SessionRow, command: str | None, job: str | None, declarations: _Declarations
) -> MappedSession:
    """A ``job_runner`` row: it agrees only with the retired run-job command or with no command."""
    if command not in (None, _RUN_JOB_COMMAND):
        return _unmapped(row, MappingReason.RECORDED_VALUES_DISAGREE)
    if not job:
        return _unmapped(row, MappingReason.UNNAMED_COMBINATION)
    if _PROCEDURE_ID_MARKER in job:
        declared = declarations.role(job, row.project_path)
        if declared is None:
            return _unmapped(row, MappingReason.PROCEDURE_DECLARES_NO_ROLE)
        naming = _jobs_naming(job, declarations.jobs(row.project_path))
        if len(naming) != 1:
            return _unmapped(row, MappingReason.PROCEDURE_NOT_ONE_JOB)
        return MappedSession(
            role=declared.role,
            job=naming[0],
            command=job,
            declaration=DeclarationEvidence(DeclarationSource.RECORDED_PROCEDURE_ID, job, naming[0], declared.status),
        )
    procedure_id = _job_procedure(job, declarations.jobs(row.project_path))
    if procedure_id is None:
        return _unmapped(row, MappingReason.JOB_NAMES_NO_DECLARATION)
    declared = declarations.role(procedure_id, row.project_path)
    if declared is None:
        return _unmapped(row, MappingReason.PROCEDURE_DECLARES_NO_ROLE)
    return MappedSession(
        role=declared.role,
        job=job,
        command=procedure_id,
        declaration=DeclarationEvidence(DeclarationSource.CONFIGURED_JOB, procedure_id, job, declared.status),
    )


def _ledger_entry(row: SessionRow, mapped: MappedSession) -> dict[str, str | None]:
    return {
        LedgerKey.SESSION_ID: row.session_id,
        LedgerKey.SYSTEM_ROLE: row.system_role,
        LedgerKey.JOB: row.job,
        LedgerKey.COMMAND: row.command,
        LedgerKey.WORKING_SLUG: row.working_slug,
        LedgerKey.REASON: mapped.reason.value if mapped.reason is not None else None,
    }


def _combination_entry(
    row: SessionRow, mapped: MappedSession, sessions: int
) -> dict[str, str | int | bool | dict[str, str | None] | None]:
    """One distinct recorded combination, how many sessions carried it, and what it became."""
    return {
        LedgerKey.SYSTEM_ROLE: row.system_role,
        LedgerKey.JOB: row.job,
        LedgerKey.COMMAND: row.command,
        LedgerKey.HAS_WORKING_SLUG: bool(row.working_slug),
        LedgerKey.SESSIONS: sessions,
        LedgerKey.RESULT_ROLE: mapped.role,
        LedgerKey.RESULT_JOB: mapped.job,
        LedgerKey.RESULT_COMMAND: mapped.command,
        LedgerKey.REASON: mapped.reason.value if mapped.reason is not None else None,
        LedgerKey.DECLARATION: mapped.declaration.to_dict() if mapped.declaration is not None else None,
    }


def _publish_ledger(report_json: str) -> None:
    """Make the report durable where an operator reads it: write beside it, flush, fsync, rename into place.

    A failure raises here, before any row has changed.
    """
    _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = _LEDGER_PATH.with_name(_LEDGER_PATH.name + _LEDGER_TEMPORARY_SUFFIX)
    with temporary.open(_LEDGER_WRITE_MODE, encoding=_LEDGER_ENCODING) as handle:
        handle.write(report_json)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(_LEDGER_PATH)


async def _table_exists(db: aiosqlite.Connection, table: str) -> bool:
    async with db.execute(_TABLE_EXISTS_SQL, (table,)) as cursor:
        return await cursor.fetchone() is not None


async def _session_columns(db: aiosqlite.Connection) -> set[str]:
    async with db.execute(_SESSION_COLUMNS_SQL) as cursor:
        return {str(row[0]) for row in await cursor.fetchall()}


async def _planned_handovers(db: aiosqlite.Connection, roles: dict[str, str | None]) -> list[tuple[str, str]]:
    """Each persisted launch intent of a migrated row, carrying its row's result role; nothing is written."""
    if not await _table_exists(db, _HANDOVERS_TABLE):
        return []
    async with db.execute(_SELECT_HANDOVERS_SQL) as cursor:
        handovers = [(str(row[0]), str(row[1])) for row in await cursor.fetchall()]
    planned: list[tuple[str, str]] = []
    for session_id, raw in handovers:
        if session_id not in roles:
            continue
        try:
            intent = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(intent, dict):
            continue
        intent[_HANDOVER_JOB_ROLE_KEY] = roles[session_id]
        planned.append((session_id, json.dumps(intent)))
    return planned


async def up(db: aiosqlite.Connection) -> None:
    """Map every stored session, publish the report, then change the rows in one transaction.

    The order keeps the original values recoverable: (1) every row and every persisted launch intent is read and
    mapped without a write — a declaration source the mapping needs and cannot read raises ``MigrationNotReady``
    here, with every row as recorded and the migration unrecorded; (2) the ledger is made durable — a failure raises with every row as recorded and the
    migration unrecorded, so the next start reruns it from the same rows; (3) the role column is added, the rows
    and launch intents rewritten and ``system_role`` retired in one transaction, committed once; (4) the runner
    records the migration applied. A start that finds ``system_role`` already retired returns without touching the
    ledger.
    """
    columns = await _session_columns(db)
    if _SYSTEM_ROLE_COLUMN not in columns:
        if _ROLE_COLUMN not in columns:
            await db.execute(_ADD_ROLE_SQL)
        await db.commit()
        return

    async with db.execute(_SELECT_SESSIONS_SQL) as cursor:
        rows = [SessionRow(str(r[0]), r[1], r[2], r[3], r[4], r[5]) for r in await cursor.fetchall()]
    try:
        declarations = _Declarations()
        mapped_rows = [(row, _map_row(row, declarations)) for row in rows]
    except MigrationNotReady as exc:
        logger.error(
            _NOT_READY_EVENT,
            migration=_MIGRATION_NAME,
            source=exc.source.value,
            location=str(exc.location),
            procedure_id=exc.procedure_id,
            reason=exc.reason,
        )
        raise

    unmapped: list[dict[str, str | None]] = []
    role_counts: dict[str, int] = defaultdict(int)
    migrated_roles: dict[str, str | None] = {}
    combination_counts: dict[tuple[object, ...], int] = defaultdict(int)
    combination_samples: dict[tuple[object, ...], tuple[SessionRow, MappedSession]] = {}
    for row, mapped in mapped_rows:
        migrated_roles[row.session_id] = mapped.role
        combination_key = (
            row.system_role,
            row.job,
            row.command,
            bool(row.working_slug),
            mapped.role,
            mapped.job,
            mapped.command,
            mapped.reason,
            mapped.declaration,
        )
        combination_counts[combination_key] += 1
        combination_samples.setdefault(combination_key, (row, mapped))
        if mapped.role is not None:
            role_counts[mapped.role] += 1
        if mapped.reason is not None:
            unmapped.append(_ledger_entry(row, mapped))
    handovers = await _planned_handovers(db, migrated_roles)

    report = {
        LedgerKey.MIGRATED_SESSIONS: len(rows),
        LedgerKey.ROLES: dict(role_counts),
        LedgerKey.COMBINATIONS: [
            _combination_entry(sample_row, sample_mapped, combination_counts[key])
            for key, (sample_row, sample_mapped) in combination_samples.items()
        ],
        LedgerKey.UNMAPPED: unmapped,
    }
    _publish_ledger(json.dumps(report, indent=2, sort_keys=True))

    await db.execute(_BEGIN_SQL)
    try:
        if _ROLE_COLUMN not in columns:
            await db.execute(_ADD_ROLE_SQL)
        for row, mapped in mapped_rows:
            await db.execute(_UPDATE_SESSION_SQL, (mapped.role, mapped.job, mapped.command, row.session_id))
        for session_id, intent_json in handovers:
            await db.execute(_UPDATE_HANDOVER_SQL, (intent_json, session_id))
        await db.execute(_DROP_SYSTEM_ROLE_SQL)
    except Exception:
        await db.rollback()
        raise
    await db.commit()
    logger.info(_MIGRATION_COMPLETE_TEMPLATE, len(rows), len(unmapped), _LEDGER_PATH)


async def down(db: aiosqlite.Connection) -> None:
    """Rollback restores the pre-migration deployment together with its data."""
    del db
