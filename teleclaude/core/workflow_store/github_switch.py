"""Switch a project to its GitHub workflow store and move its open local work."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import cast
from uuid import uuid4

from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from instrukt_ai_logging import get_logger

from teleclaude.config.loader import (
    github_actor_for_app_id,
    load_declared_project_config,
    save_project_config,
)
from teleclaude.config.project_models import TodoStoreBackend, TodoStoreConfig
from teleclaude.config.schema import ProjectConfig
from teleclaude.constants import TodoStatus
from teleclaude.core.db import Db
from teleclaude.core.integration.state_machine import (
    IntegrationRecoveryRefused,
    hold_integration_for_todo_recovery,
)
from teleclaude.core.next_machine.runtime.sessions import is_live_session_id
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.core.todos_db._adapter import TodosDb
from teleclaude.core.todos_db._working_copy import (
    WorkingCopyItemSnapshot,
    WorkingCopyMoveSet,
)
from teleclaude.core.todos_db_path import todos_db_path
from teleclaude.core.workflow_store.github import GitHubIdentityRefused, GitHubRepositoryIdentity
from teleclaude.core.workflow_store.github_io import GitHubIORefused, GitHubMutationPacing
from teleclaude.core.workflow_store.github_record import (
    WORKFLOW_COMMENT_BODY_LIMIT,
    LedgerCommit,
    LedgerProjectRecord,
    LedgerRecordTable,
    Row,
    render_ledger_commit,
)
from teleclaude.core.workflow_store.github_reflection import is_repository_work
from teleclaude.core.workflow_store.github_store import GitHubWorkflowStore, get_github_workflow_store
from teleclaude.core.workflow_store.github_sync import GitHubWorkflowSyncRefused
from teleclaude.core.workflow_store.local_store import get_local_workflow_store
from teleclaude.core.workflow_store.selection import selected_workflow_store_config
from teleclaude.github.credentials import GitHubCredentialRefused, issue_github_installation_credential
from teleclaude.paths import ConfigFileName
from teleclaude.types.github_binding import GitHubActorAssignment
from teleclaude.types.todos import FinalizeStatus

_WRITE_PERMISSIONS: AppPermissionsType = {"issues": "write"}
_SWITCH_EVENT = "todo_store_switch_completed"
_EMPTY = ""
_FINALIZE = "finalize"
_INTEGRATION_PHASE = "integration_phase"
_STARTED = "started"
_ACTIVE_RUNNER = "active_runner"
_SLUG = "slug"
_ID = "id"
_STATUS = "status"
_GROUP_ID = "group_id"
_DEPENDS_ON = "depends_on"
_SIZE_CHECK_ROW_ID = 9_223_372_036_854_775_807
_REPORT_JOIN = ", "
_REPORT_LINES = "\n"
_REPORT_MOVED = "moved: {}"
_REPORT_PRESENT = "already present: {}"
_REPORT_DETACHED = "moved without finished group: {}"
_REPORT_KEPT = "kept on this computer: {}"
_REPORT_NOT_MOVED = "not moved: {}"
_REPORT_PROJECT_RECORDS = "project records moved: {}"
_REPORT_STOP_CAUSE = "stop cause: {}"
_REPORT_COMPLETE = "move complete: {}"
_REPORT_ITEM_REASON = "{} ({})"
_READINESS_MISSING_DECLARATION = "project declaration is missing"
_READINESS_MISSING_REPOSITORY = "todos.repository is undeclared"
_READINESS_MISSING_APP = "todos.app is undeclared"
_READINESS_UNKNOWN_APP = "todos.app is not present in the machine App inventory"
_READINESS_GITHUB_REFUSED = "GitHub issue-write readiness refused: {}"
_SWITCH_LIVE_WORK = "live workflow work prevents switching: {}"
_SWITCH_LIVE_SEPARATOR = "; "
_SWITCH_INTEGRATION_IDLE = "integration is not idle: {}"
_LIVE_CLAIM = "{} claimed by {}"
_LIVE_SESSIONS = "{} has open sessions: {}"
_LIVE_OPERATIONS = "{} has running operations: {}"
_LIVE_INTEGRATION = "{} is ready for or being integrated"
_SOURCE_DISAPPEARED = "source snapshot disappeared"
_SLUG_CONFLICT = "slug belongs to item {}"
_STORE_PREPARE_REFUSED = "store refused while preparing the GitHub store: {}"
_ITEM_RESTORE_REFUSED = "store refused while restoring {}: {}"
_PROJECT_RESTORE_REFUSED = "store refused while restoring project records: {}"
_ITEM_NOT_REACHED = "not reached: the run stopped"
_PROJECT_RECORD_ID_REQUIRED = "project record is missing its persisted row id"
_SWITCH_ITEM = "switch"
_TODOS_FIELD = "todos"
_STORE_FIELD = "store"
_EXPECTED_REFUSALS = (
    GitHubIORefused,
    GitHubWorkflowSyncRefused,
    GitHubIdentityRefused,
    GitHubCredentialRefused,
)
logger = get_logger(__name__)


@dataclass(frozen=True)
class SwitchReport:
    """Outcome of one repeatable local-to-GitHub migration run."""

    moved: tuple[str, ...] = ()
    already_present: tuple[str, ...] = ()
    detached: tuple[str, ...] = ()
    kept_on_computer: tuple[str, ...] = ()
    not_moved: tuple[tuple[str, str], ...] = ()
    project_records_moved: int = 0
    stop_cause: str | None = None
    complete: bool = False

    def render(self) -> str:
        """Render the durable operation result without item content."""
        details = [
            _REPORT_MOVED.format(_REPORT_JOIN.join(self.moved) or _EMPTY),
            _REPORT_PRESENT.format(_REPORT_JOIN.join(self.already_present) or _EMPTY),
            _REPORT_DETACHED.format(_REPORT_JOIN.join(self.detached) or _EMPTY),
            _REPORT_KEPT.format(_REPORT_JOIN.join(self.kept_on_computer) or _EMPTY),
            _REPORT_NOT_MOVED.format(
                _REPORT_JOIN.join(_REPORT_ITEM_REASON.format(slug, reason) for slug, reason in self.not_moved) or _EMPTY
            ),
            _REPORT_PROJECT_RECORDS.format(self.project_records_moved),
            _REPORT_STOP_CAUSE.format(self.stop_cause or _EMPTY),
            _REPORT_COMPLETE.format(self.complete),
        ]
        return _REPORT_LINES.join(details)


@dataclass
class _MoveCounts:
    moved: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    detached: list[str] = field(default_factory=list)
    kept_on_computer: list[str] = field(default_factory=list)
    not_moved: list[tuple[str, str]] = field(default_factory=list)
    project_records_moved: int = 0
    stop_cause: str | None = None


class _ReadinessRefused(RuntimeError):
    """A GitHub repository credential could not be issued for the declaration."""


async def switch_project_to_github(
    db: Db,
    project_root: str | Path,
    operation_id: str,
) -> SwitchReport:
    """Switch the selected project and continue copying its frozen local work."""
    started_at = perf_counter()
    root = resolve_project_state_root(project_root)
    readiness = await _check_readiness(root)
    if isinstance(readiness, SwitchReport):
        return _record_report(root, readiness, started_at)
    declaration, selected = readiness
    local_store = cast(TodosDb, await get_local_workflow_store(root)) if todos_db_path(root).is_file() else None
    if selected.store is TodoStoreBackend.LOCAL:
        refusal = await _switch_selection(db, root, declaration, local_store, operation_id)
        if refusal is not None:
            return _record_report(root, refusal, started_at)
    try:
        target = cast(GitHubWorkflowStore, await get_github_workflow_store(root))
    except _EXPECTED_REFUSALS as error:
        selected_set = (
            await local_store.migration_move_set() if local_store is not None else WorkingCopyMoveSet((), frozenset())
        )
        report = await _stopped_before_move(local_store, selected_set, error)
    else:
        report = (
            await _move_local_source(local_store, target) if local_store is not None else SwitchReport(complete=True)
        )
    return _record_report(root, report, started_at)


def _record_report(root: Path, report: SwitchReport, started_at: float) -> SwitchReport:
    logger.info(
        _SWITCH_EVENT,
        project=str(root),
        moved=len(report.moved),
        already_present=len(report.already_present),
        not_moved=len(report.not_moved),
        project_records_moved=report.project_records_moved,
        stop_cause=report.stop_cause,
        duration_ms=int((perf_counter() - started_at) * 1000),
    )
    return report


async def _check_readiness(
    root: Path,
) -> tuple[ProjectConfig, TodoStoreConfig] | SwitchReport:
    declaration = load_declared_project_config(root)
    if declaration is None:
        return _refused(_READINESS_MISSING_DECLARATION)
    selected = selected_workflow_store_config(root)
    if selected.repository is None:
        return _refused(_READINESS_MISSING_REPOSITORY)
    if selected.app is None:
        return _refused(_READINESS_MISSING_APP)
    assignment = github_actor_for_app_id(selected.app)
    if assignment is None:
        return _refused(_READINESS_UNKNOWN_APP)
    repository = GitHubRepositoryIdentity(
        project_path=root,
        repository_id=selected.repository.id,
        repository=selected.repository.full_name,
    )
    try:
        await _verify_issue_write(assignment, repository)
    except _ReadinessRefused as error:
        return _refused(_READINESS_GITHUB_REFUSED.format(error))
    return declaration, selected


async def _verify_issue_write(assignment: GitHubActorAssignment, repository: GitHubRepositoryIdentity) -> None:
    try:
        await issue_github_installation_credential(assignment, repository, _WRITE_PERMISSIONS)
    except GitHubCredentialRefused as error:
        raise _ReadinessRefused(error.reason.value) from error


async def _switch_selection(
    db: Db,
    root: Path,
    declaration: ProjectConfig,
    local_store: TodosDb | None,
    operation_id: str,
) -> SwitchReport | None:
    if local_store is None:
        _write_github_selection(root, declaration)
        return None
    try:
        with hold_integration_for_todo_recovery(str(root), operation_id):
            async with local_store.hold_write_window():
                live_work = await _find_live_work(db, local_store, str(root), operation_id)
                if live_work:
                    return _refused(_SWITCH_LIVE_WORK.format(_SWITCH_LIVE_SEPARATOR.join(live_work)))
                _write_github_selection(root, declaration)
    except IntegrationRecoveryRefused as error:
        return _refused(_SWITCH_INTEGRATION_IDLE.format(error))
    return None


def _write_github_selection(root: Path, declaration: ProjectConfig) -> None:
    updated = declaration.model_copy(
        update={_TODOS_FIELD: declaration.todos.model_copy(update={_STORE_FIELD: TodoStoreBackend.GITHUB})}
    )
    save_project_config(root / ConfigFileName.OVERLAY, updated)


async def _find_live_work(db: Db, store: TodosDb, cwd: str, operation_id: str) -> list[str]:
    items = await store.list_todo(include_icebox=True, include_holders=True)
    findings: list[str] = []
    for item in items:
        item_row = cast(Mapping[str, object], item)
        if item_row[_STATUS] not in (TodoStatus.ACTIVE.value, TodoStatus.ICEBOX.value, TodoStatus.HOLDER.value):
            continue
        slug = str(item_row[_SLUG])
        state = await store.read_state_by_id(str(item_row[_ID]))
        claimant = state.get(_ACTIVE_RUNNER) if state else None
        if isinstance(claimant, str) and await is_live_session_id(db, claimant):
            findings.append(_LIVE_CLAIM.format(slug, claimant))
        sessions = await db.find_open_sessions_bound_to_todo(old_slug=slug, cwd=cwd)
        if sessions:
            findings.append(
                _LIVE_SESSIONS.format(slug, _REPORT_JOIN.join(sorted(session.session_id for session in sessions)))
            )
        operations = await db.find_nonterminal_operations_bound_to_todo(
            old_slug=slug,
            cwd=cwd,
            exclude_operation_id=operation_id,
        )
        if operations:
            findings.append(
                _LIVE_OPERATIONS.format(slug, _REPORT_JOIN.join(sorted(op.operation_id for op in operations)))
            )
        finalize = state.get(_FINALIZE) if state else None
        finalize_status = finalize.get(_STATUS) if isinstance(finalize, Mapping) else None
        integration_phase = state.get(_INTEGRATION_PHASE) if state else None
        if finalize_status == FinalizeStatus.READY.value or integration_phase == _STARTED:
            findings.append(_LIVE_INTEGRATION.format(slug))
    return findings


async def _move_local_source(store: TodosDb, target: GitHubWorkflowStore) -> SwitchReport:
    selected = await store.migration_move_set()
    source_records = await store.migration_project_records()
    source_snapshots = {
        item_id: snapshot
        for item_id in selected.item_ids
        if (snapshot := await store.migration_item_snapshot(item_id)) is not None
    }
    moved_slugs = {str(snapshot.todo[_SLUG]) for snapshot in source_snapshots.values()}
    counts = _MoveCounts()
    async with target.paced_mutations() as pacing:
        target_items = await target.list_todo(include_icebox=True, include_holders=True)
        target_by_slug = {str(cast(Mapping[str, object], item)[_SLUG]): item for item in target_items}
        target_ids = await target.migration_held_item_ids()
        target_records = await _read_target_project_records(target)
        for index, item_id in enumerate(selected.item_ids):
            snapshot = source_snapshots.get(item_id)
            if snapshot is None:
                counts.not_moved.append((item_id, _SOURCE_DISAPPEARED))
                continue
            slug = str(snapshot.todo[_SLUG])
            repository_work = is_repository_work(snapshot.state)
            if item_id in target_ids:
                if repository_work:
                    counts.already_present.append(slug)
                else:
                    counts.kept_on_computer.append(slug)
                continue
            conflict = target_by_slug.get(slug)
            if conflict is not None:
                conflict_id = cast(Mapping[str, object], conflict)[_ID]
                counts.not_moved.append((slug, _SLUG_CONFLICT.format(conflict_id)))
                continue
            try:
                await target.restore_migration_item(_prepare_snapshot(snapshot, selected, moved_slugs))
            except _EXPECTED_REFUSALS as error:
                reason = _failure_reason(error)
                counts.not_moved.append((slug, reason))
                counts.not_moved.extend(
                    await _unreached_items(store, selected.item_ids[index + 1 :], _ITEM_NOT_REACHED)
                )
                counts.stop_cause = _ITEM_RESTORE_REFUSED.format(slug, reason)
                break
            target_ids = target_ids | {item_id}
            if repository_work:
                counts.moved.append(slug)
            else:
                counts.kept_on_computer.append(slug)
            if repository_work and item_id in selected.detached_item_ids:
                counts.detached.append(slug)
            await pacing.wait_between_items()
        if counts.stop_cause is None:
            await _move_project_records(target, source_records, target_records, pacing, counts)
    return SwitchReport(
        moved=tuple(counts.moved),
        already_present=tuple(counts.already_present),
        detached=tuple(counts.detached),
        kept_on_computer=tuple(counts.kept_on_computer),
        not_moved=tuple(counts.not_moved),
        project_records_moved=counts.project_records_moved,
        stop_cause=counts.stop_cause,
        complete=not counts.not_moved and counts.stop_cause is None,
    )


async def _unreached_items(store: TodosDb, item_ids: tuple[str, ...], reason: str) -> list[tuple[str, str]]:
    unreached: list[tuple[str, str]] = []
    for item_id in item_ids:
        snapshot = await store.migration_item_snapshot(item_id)
        slug = str(snapshot.todo[_SLUG]) if snapshot is not None else item_id
        unreached.append((slug, reason))
    return unreached


async def _stopped_before_move(store: TodosDb | None, selected: WorkingCopyMoveSet, error: Exception) -> SwitchReport:
    reason = _failure_reason(error)
    items = await _unreached_items(store, selected.item_ids, _ITEM_NOT_REACHED) if store is not None else []
    return SwitchReport(not_moved=tuple(items), stop_cause=_STORE_PREPARE_REFUSED.format(reason))


async def _move_project_records(
    target: GitHubWorkflowStore,
    source_records: tuple[tuple[str, Mapping[str, object]], ...],
    target_records: dict[str, set[tuple[tuple[str, object], ...]]],
    pacing: GitHubMutationPacing,
    counts: _MoveCounts,
) -> None:
    pending: list[tuple[str, Mapping[str, object]]] = []
    for table, record in source_records:
        values = _project_record_values(record)
        if values in target_records.get(table, set()):
            continue
        candidate = [*pending, (table, record)]
        if (
            _ledger_body_size([_ledger_project_record(t, r, _record_id(t, r)) for t, r in candidate])
            > WORKFLOW_COMMENT_BODY_LIMIT
        ):
            if pending:
                try:
                    await _restore_project_batch(target, pending)
                except _EXPECTED_REFUSALS as error:
                    counts.stop_cause = _PROJECT_RESTORE_REFUSED.format(_failure_reason(error))
                    return
                counts.project_records_moved += len(pending)
                for moved_table, moved_record in pending:
                    target_records.setdefault(moved_table, set()).add(_project_record_values(moved_record))
                pending = []
                await pacing.wait_between_items()
            candidate = [(table, record)]
            if (
                _ledger_body_size([_ledger_project_record(table, record, _record_id(table, record))])
                > WORKFLOW_COMMENT_BODY_LIMIT
            ):
                raise ValueError(_RECORD_TOO_LARGE)
        pending = candidate
    if pending:
        try:
            await _restore_project_batch(target, pending)
        except _EXPECTED_REFUSALS as error:
            counts.stop_cause = _PROJECT_RESTORE_REFUSED.format(_failure_reason(error))
            return
        counts.project_records_moved += len(pending)
        await pacing.wait_between_items()


async def _restore_project_batch(target: GitHubWorkflowStore, records: list[tuple[str, Mapping[str, object]]]) -> None:
    await target.restore_migration_project_records(tuple(records))


def _record_id(table: str, record: Mapping[str, object]) -> str:
    return _SWITCH_RECORD_FORMAT.format(table, record.get(_ID))


_RECORD_TOO_LARGE = "one project record exceeds the workflow comment size limit"
_SWITCH_RECORD_FORMAT = "github-store-switch:{}:{}"


def _failure_reason(error: Exception) -> str:
    if isinstance(error, GitHubIORefused):
        return str(error)
    if isinstance(error, (GitHubCredentialRefused, GitHubIdentityRefused)):
        return error.reason.value
    if isinstance(error, GitHubWorkflowSyncRefused):
        return str(error)
    return type(error).__name__


async def _read_target_project_records(
    store: GitHubWorkflowStore,
) -> dict[str, set[tuple[tuple[str, object], ...]]]:
    records = await store.migration_project_records()
    grouped: dict[str, set[tuple[tuple[str, object], ...]]] = {}
    for table, record in records:
        grouped.setdefault(table, set()).add(_project_record_values(record))
    return grouped


def _ledger_project_record(table: str, record: Mapping[str, object], remote_id: str) -> LedgerProjectRecord:
    row_id = record.get(_ID)
    if not isinstance(row_id, int) or row_id <= 0:
        raise ValueError(_PROJECT_RECORD_ID_REQUIRED)
    data = cast(Row, {key: value for key, value in record.items() if key != _ID})
    return LedgerProjectRecord(
        table=LedgerRecordTable(table),
        row_id=_SIZE_CHECK_ROW_ID,
        remote_record_id=remote_id,
        data=data,
    )


def _ledger_body_size(records: list[LedgerProjectRecord]) -> int:
    commit = LedgerCommit(transaction_id=uuid4().hex, project_records=records)
    return len(render_ledger_commit(commit))


def _project_record_values(record: Mapping[str, object]) -> tuple[tuple[str, object], ...]:
    return tuple(sorted((key, value) for key, value in record.items() if key != _ID))


def _prepare_snapshot(
    snapshot: WorkingCopyItemSnapshot, selected: WorkingCopyMoveSet, moved_slugs: set[str]
) -> WorkingCopyItemSnapshot:
    included = set(selected.item_ids)
    todo = dict(snapshot.todo)
    group_id = todo.get(_GROUP_ID)
    if group_id is not None and str(group_id) not in included:
        todo[_GROUP_ID] = None
    dependencies = tuple(
        dependency for dependency in snapshot.dependencies if dependency.get(_DEPENDS_ON) in moved_slugs
    )
    return WorkingCopyItemSnapshot(
        item_id=snapshot.item_id,
        todo=todo,
        state=snapshot.state,
        dependencies=dependencies,
        artifacts=snapshot.artifacts,
        versions=snapshot.versions,
    )


def _refused(reason: str) -> SwitchReport:
    return SwitchReport(not_moved=((_SWITCH_ITEM, reason),), stop_cause=reason)
