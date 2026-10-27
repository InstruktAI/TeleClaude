"""Commit local working-copy mutations to the authoritative GitHub record."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Container, Mapping
from pathlib import Path
from typing import Any, cast

from instrukt_ai_logging import get_logger
from sqlalchemy.orm import Session

from teleclaude.core.todos_db._ledger_knowledge import record_ledger_commits
from teleclaude.core.todos_db._working_copy import (
    WorkingCopyChanges,
    WorkingCopyField,
    WorkingCopyItemSnapshot,
    artifact_remote_version_id,
    clear_pending_changes,
    issue_relation_dependents,
    item_bookkeeping,
    item_snapshot,
    item_unverifiable,
    mark_project_record_pushed,
    mark_reflection_owed,
    pending_changes,
    project_records,
    project_remote_record_id,
    prune_deleted_artifact_versions,
    read_repository_bookkeeping,
    save_artifact_comment_ids,
    save_item_bookkeeping,
    save_ledger_issue,
)
from teleclaude.core.workflow_store import github_reflection as _github_reflection
from teleclaude.core.workflow_store.github import GitHubRepositoryIdentity
from teleclaude.core.workflow_store.github_io import (
    GitHubComment,
    GitHubOperation,
    GitHubWorkflowIO,
)
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused
from teleclaude.core.workflow_store.github_item_trust import validate_revision_content
from teleclaude.core.workflow_store.github_ledger import GitHubLedgerRefused, find_ledger
from teleclaude.core.workflow_store.github_ledger_commits import LedgerCommitView
from teleclaude.core.workflow_store.github_pull_request_io import GitHubPullRequestIO
from teleclaude.core.workflow_store.github_push_deadline import (
    COMMIT_POINT_SENT_KEY as _COMMIT_POINT_SENT_KEY,
)
from teleclaude.core.workflow_store.github_push_deadline import (
    PUSH_DEADLINE_KEY as _PUSH_DEADLINE_KEY,
)
from teleclaude.core.workflow_store.github_push_deadline import (
    PushDeadline,
    await_within_push_deadline,
    begin_push_deadline,
    push_deadline_expired,
)
from teleclaude.core.workflow_store.github_record import (
    ArtifactHistoryAction,
    ArtifactHistoryNode,
    ArtifactPointer,
    ItemRevision,
    LedgerCommit,
    LedgerItem,
    LedgerProjectRecord,
    LedgerRecordTable,
    PendingRevision,
    WorkflowField,
    WorkflowRecord,
    WorkflowTodoStatus,
    effective_revision,
    join_content_comments,
    latest_artifact_pointer,
    make_item_revision,
    parse_content_comment,
    parse_record_comment,
    render_ledger_commit,
    render_record_comment,
    render_standalone_artifact_history_comment,
    resolve_artifact_history,
    split_artifact_version_comments,
    split_state_version_comments,
    trusted_comment_body,
)
from teleclaude.core.workflow_store.github_reflection import INPUT_ARTIFACT_NAME
from teleclaude.core.workflow_store.github_reflection_queue import (
    dispatch_staged_pull_requests,
    dispatch_staged_reflections,
    stage_issue_reflections,
    stage_pull_request_reflections,
)
from teleclaude.types.github_binding import GitHubActorAssignment

_CONFLICT_REFRESH_KEY = "github_store_conflict_refresh"
_CONFLICT_DRIVER_KEY = "github_store_conflict_driver"
_EMPTY = ""
_ENCODING = "utf-8"
_MAX_INLINE_STATE = 40_000
_STATE_NAME = WorkflowField.STATE
_RUN_ASYNC_METHOD = "run_async"
_LEDGER_TITLE = "TeleClaude workflow ledger"
_LEDGER_DESCRIPTION = "Project-level workflow records."
_CONFLICT_REFRESH_FAILED = "github_store_conflict_refresh_failed"
_LEGACY_VERSION_ID = "legacy-{}-{}"
logger = get_logger(__name__)


class GitHubWorkflowPush:
    """Make each local transaction visible at one GitHub issue or ledger commit point."""

    def __init__(
        self,
        db_path: str | Path,
        repository: GitHubRepositoryIdentity,
        assignment: GitHubActorAssignment,
        io: GitHubWorkflowIO,
        pull_requests: GitHubPullRequestIO,
    ) -> None:
        self.db_path = Path(db_path)
        self.repository = repository
        self.assignment = assignment
        self.io = io
        self.pull_requests = pull_requests
        self._refresh_callback: Callable[[], Awaitable[int]] | None = None

    def set_conflict_refresh(self, callback: Callable[[], Awaitable[int]]) -> None:
        """Attach the store's post-rollback refresh operation."""
        self._refresh_callback = callback

    def before_commit(self, session: Session) -> None:
        """Push every captured row before SQLite can commit the workflow transaction."""
        changes = pending_changes(session)
        if not changes.item_ids and not changes.project_records:
            return
        # A paced push (the GitHub store switch) publishes at one write per second and keeps the switch's own limits.
        session.info[_PUSH_DEADLINE_KEY] = None if self.io.paced else begin_push_deadline()
        session.info.pop(_COMMIT_POINT_SENT_KEY, None)
        try:
            self._push_changes(session, changes)
        finally:
            session.info.pop(_PUSH_DEADLINE_KEY, None)
            session.info.pop(_COMMIT_POINT_SENT_KEY, None)

    def _push_changes(self, session: Session, changes: WorkingCopyChanges) -> None:
        ledger = read_repository_bookkeeping(session)
        cached_ledger_issue = _int_or_none(ledger.get(WorkflowField.LEDGER_ISSUE_NUMBER))
        ledger_issue_number = self._discover_ledger(session, cached_ledger_issue)
        ledger_commits = LedgerCommitView(
            session, self.assignment.actor.login, self._ledger_reader(session, ledger_issue_number)
        )
        record_comments: dict[int, GitHubComment] = {}
        snapshots: list[
            tuple[WorkingCopyItemSnapshot, int, int | None, str, int, ItemRevision, WorkflowRecord | None, int | None]
        ] = []
        reflection_rows: list[tuple[int, str, WorkingCopyItemSnapshot]] = []
        newly_issued_item_ids: set[str] = set()

        for item_id in changes.item_ids:
            existing_bookkeeping = item_bookkeeping(session, item_id)
            had_issue = (
                _int_or_none(existing_bookkeeping.get(WorkflowField.ISSUE_NUMBER)) is not None
                if existing_bookkeeping
                else False
            )
            prepared = self._prepare_item_revision(session, item_id, ledger_commits, record_comments)
            if prepared is None:
                continue
            snapshot, issue_number, issue_id, node_id, base_revision, revision, old_record, record_comment_id = prepared
            if issue_number is not None:
                reflection_rows.append((issue_number, item_id, snapshot))
            if revision is not None and issue_number is not None and node_id is not None:
                snapshots.append(
                    (snapshot, issue_number, issue_id, node_id, base_revision, revision, old_record, record_comment_id)
                )
                if not had_issue:
                    newly_issued_item_ids.add(item_id)

        self._append_relation_reflections(session, reflection_rows, newly_issued_item_ids)

        changed_project_records = project_records(session, changes.project_records)
        if not snapshots and not changed_project_records:
            for _issue_number, item_id, _snapshot in reflection_rows:
                mark_reflection_owed(session, item_id)
            clear_pending_changes(session)
            return
        ledger_commit_needed = len(snapshots) != 1 or bool(changed_project_records)
        transaction_id = str(uuid.uuid4()) if ledger_commit_needed else None
        record_ids: list[tuple[str, int, int | None, str, int | None, int]] = []
        ledger_items: list[LedgerItem] = []

        for (
            snapshot,
            issue_number,
            issue_id,
            issue_node_id,
            _base_revision,
            revision,
            old_record,
            record_comment_id,
        ) in snapshots:
            committed = old_record.committed if old_record is not None else _empty_revision(revision.item_id)
            record = (
                WorkflowRecord(
                    committed=committed,
                    pending=PendingRevision(transaction_id=transaction_id, revision=revision),
                )
                if transaction_id is not None
                else WorkflowRecord(committed=revision)
            )
            comment = self._write_item_record(
                session,
                issue_number,
                record_comment_id,
                record,
                record_comments,
                _state_text(snapshot.state),
                commit_point=transaction_id is None,
            )
            revision_number = revision.revision
            record_ids.append(
                (revision.item_id, issue_number, issue_id, issue_node_id, comment.database_id, revision_number)
            )
            if transaction_id is not None:
                ledger_items.append(LedgerItem(issue_number=issue_number, revision=revision_number))

        ledger_comment_id: int | None = None
        if transaction_id is not None:
            if ledger_issue_number is None:
                issue = _io_call(
                    session,
                    self.io,
                    GitHubOperation.OPEN_ISSUE,
                    _LEDGER_TITLE,
                    _LEDGER_DESCRIPTION,
                )
                ledger_issue_number = issue.number
                save_ledger_issue(session, issue.number, issue.node_id)
            project_entries = [
                LedgerProjectRecord(
                    table=LedgerRecordTable(table),
                    row_id=_int_or_none(row.get(WorkflowField.ID)) or row_id,
                    remote_record_id=project_remote_record_id(session, table, row_id),
                    data=_scalar_row({key: value for key, value in row.items() if key != WorkflowField.ID}),
                )
                for (table, row_id), (_, row) in zip(changes.project_records, changed_project_records, strict=True)
            ]
            commit = LedgerCommit(
                transaction_id=transaction_id,
                items=ledger_items,
                project_records=project_entries,
            )
            session.info[_COMMIT_POINT_SENT_KEY] = True
            ledger_comment = _io_call(
                session,
                self.io,
                GitHubOperation.CREATE_COMMENT,
                ledger_issue_number,
                render_ledger_commit(commit),
            )
            ledger_comment_id = ledger_comment.database_id
            record_ledger_commits(session, [(transaction_id, ledger_comment.database_id)])

        for item_id, issue_number, issue_id, node_id, record_comment_id, revision_number in record_ids:
            save_item_bookkeeping(
                session,
                item_id,
                issue_number=issue_number,
                issue_id=issue_id,
                node_id=node_id,
                record_comment_id=record_comment_id,
                revision=revision_number,
                base_revision=revision_number,
            )
        if ledger_comment_id is not None:
            for table, row_id in changes.project_records:
                mark_project_record_pushed(session, table, row_id, ledger_comment_id)
        settled = stage_issue_reflections(session, reflection_rows)
        stage_pull_request_reflections(session, reflection_rows)
        for _issue_number, item_id, _snapshot in reflection_rows:
            if item_id not in settled:
                mark_reflection_owed(session, item_id)
        clear_pending_changes(session)

    @staticmethod
    def _append_relation_reflections(
        session: Session,
        reflection_rows: list[tuple[int, str, WorkingCopyItemSnapshot]],
        newly_issued_item_ids: set[str],
    ) -> None:
        """Include existing issue rows whose group or dependency target just appeared."""
        reflected_item_ids = {item_id for _number, item_id, _snapshot in reflection_rows}
        for issued_item_id in newly_issued_item_ids:
            for related_item_id in issue_relation_dependents(session, issued_item_id) - reflected_item_ids:
                related_snapshot = item_snapshot(session, related_item_id)
                related_bookkeeping = item_bookkeeping(session, related_item_id)
                related_number = (
                    _int_or_none(related_bookkeeping.get(WorkflowField.ISSUE_NUMBER)) if related_bookkeeping else None
                )
                if related_snapshot is not None and related_number is not None:
                    reflection_rows.append((related_number, related_item_id, related_snapshot))
                    reflected_item_ids.add(related_item_id)

    def _prepare_item_revision(
        self,
        session: Session,
        item_id: str,
        committed_transactions: Container[str],
        record_comments: dict[int, GitHubComment],
    ) -> (
        tuple[
            WorkingCopyItemSnapshot,
            int | None,
            int | None,
            str | None,
            int,
            ItemRevision | None,
            WorkflowRecord | None,
            int | None,
        ]
        | None
    ):
        """Prepare one changed item's revision and reflection inputs before commit."""
        if item_unverifiable(session, item_id):
            raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
        prune_deleted_artifact_versions(session, item_id)
        snapshot = item_snapshot(session, item_id, unpushed_only=True)
        bookkeeping = item_bookkeeping(session, item_id)
        issue_number = _int_or_none(bookkeeping.get(WorkflowField.ISSUE_NUMBER)) if bookkeeping else None
        issue_id = _int_or_none(bookkeeping.get(WorkingCopyField.ISSUE_ID)) if bookkeeping else None
        node_id = _string_or_none(bookkeeping.get(WorkflowField.NODE_ID)) if bookkeeping else None
        record_comment_id = _int_or_none(bookkeeping.get(WorkflowField.RECORD_COMMENT_ID)) if bookkeeping else None
        base_revision = (_int_or_none(bookkeeping.get(WorkflowField.BASE_REVISION)) or 0) if bookkeeping else 0
        old_record: WorkflowRecord | None = None
        if issue_number is not None and record_comment_id is not None:
            old_record, record_comments[record_comment_id] = self._item_record(session, issue_number, record_comment_id)
        old_revision = effective_revision(old_record, committed_transactions) if old_record else None
        if old_revision is not None and old_revision.revision > base_revision:
            session.info[_CONFLICT_REFRESH_KEY] = True
            session.info[_CONFLICT_DRIVER_KEY] = session.connection().connection
            raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
        if old_revision is not None and issue_number is not None and record_comment_id is not None:
            self._verify_item_content(session, issue_number, old_revision)
        if (
            snapshot is None
            and old_revision is not None
            and not _github_reflection.is_repository_work(old_revision.state)
        ):
            return None
        if snapshot is not None and not _github_reflection.is_repository_work(snapshot.state):
            if issue_number is None:
                return None
            revision = None
            if old_revision is not None and _github_reflection.is_repository_work(old_revision.state):
                revision = make_item_revision(
                    item_id=item_id,
                    revision=old_revision.revision + 1,
                    todo=snapshot.todo,
                    state=snapshot.state,
                    dependencies=snapshot.dependencies,
                    artifact_pointers=old_revision.artifacts,
                )
            return snapshot, issue_number, issue_id, node_id, base_revision, revision, old_record, record_comment_id
        committed_pointers, old_record = self._compact_old_record(
            session, item_id, issue_number, old_record, committed_transactions
        )
        pointers = {name: list(versions) for name, versions in committed_pointers.items()}
        if snapshot is None:
            if old_revision is None or issue_number is None or node_id is None:
                return None
            input_content = self._read_item_content(session, issue_number, old_revision, INPUT_ARTIFACT_NAME)
            todo_row = {**old_revision.todo, WorkflowField.STATUS: WorkflowTodoStatus.PURGED}
            revision = old_revision.model_copy(
                update={
                    WorkflowField.REVISION: old_revision.revision + 1,
                    WorkflowField.TODO: todo_row,
                    WorkflowField.ARTIFACTS: committed_pointers,
                }
            )
            snapshot = WorkingCopyItemSnapshot(
                item_id=item_id,
                todo=todo_row,
                state=old_revision.state,
                dependencies=tuple(old_revision.dependencies),
                artifacts=({WorkflowField.NAME: INPUT_ARTIFACT_NAME, WorkflowField.CONTENT: input_content},),
                versions=(),
            )
            return snapshot, issue_number, issue_id, node_id, base_revision, revision, old_record, record_comment_id
        if issue_number is None or node_id is None:
            issue = _io_call(
                session,
                self.io,
                GitHubOperation.OPEN_ISSUE,
                str(snapshot.todo[WorkflowField.SLUG]),
                _github_reflection.reflect_issue(snapshot).body,
            )
            issue_number, issue_id, node_id = issue.number, issue.issue_id, issue.node_id
        next_revision = (old_revision.revision if old_revision is not None else 0) + 1
        pointers = self._mark_removed_artifacts(session, item_id, issue_number, snapshot, pointers)
        created_versions = self._append_unpushed_versions(session, snapshot, issue_number, pointers)
        for version_id, name, pointer in created_versions:
            pointers[name] = [pointer]
            save_artifact_comment_ids(
                session,
                item_id,
                version_id,
                pointer.comment_ids,
                pointer.remote_version_id or _EMPTY,
                pointer.digest,
            )
        state = snapshot.state
        state_pointer = None
        if state is not None:
            state_text = state.get(WorkflowField.STATE)
            if isinstance(state_text, str) and len(state_text) > _MAX_INLINE_STATE:
                state_pointer = self._append_state_content(
                    session, item_id, next_revision, state_text, issue_number, state
                )
                state = {**state, WorkflowField.STATE: None}
        revision = make_item_revision(
            item_id,
            next_revision,
            snapshot.todo,
            state,
            snapshot.dependencies,
            pointers,
            state_content_pointer=state_pointer,
        )
        return snapshot, issue_number, issue_id, node_id, base_revision, revision, old_record, record_comment_id

    def after_commit(self, session: Session) -> None:
        """Queue issue reflections after local commit and retain failed reflections for refresh."""
        dispatch_staged_reflections(session, self.db_path, self.io)
        dispatch_staged_pull_requests(session, self.db_path, self.pull_requests)

    def _append_unpushed_versions(
        self,
        session: Session,
        snapshot: WorkingCopyItemSnapshot,
        issue_number: int,
        pointers: dict[str, list[ArtifactPointer]],
    ) -> list[tuple[int, str, ArtifactPointer]]:
        created: list[tuple[int, str, ArtifactPointer]] = []
        complete_snapshot = item_snapshot(session, snapshot.item_id)
        if complete_snapshot is None:
            raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
        ordinal_by_version: dict[int, int] = {}
        ordinal_by_name: dict[str, int] = {}
        for version in complete_snapshot.versions:
            version_id = _int_or_none(version.get(WorkflowField.VERSION_ID))
            name = _string_or_none(version.get(WorkflowField.NAME))
            if version_id is None or name is None:
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
            ordinal_by_name[name] = ordinal_by_name.get(name, 0) + 1
            ordinal_by_version[version_id] = ordinal_by_name[name]
        for version in snapshot.versions:
            version_id = _int_or_none(version.get(WorkflowField.VERSION_ID))
            name = _string_or_none(version.get(WorkflowField.NAME))
            digest = _string_or_none(version.get(WorkflowField.DIGEST))
            content = version.get(WorkflowField.CONTENT)
            if version_id is None or name is None or digest is None or not isinstance(content, str):
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
            ordinal = ordinal_by_version.get(version_id)
            if ordinal is None:
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
            remote_version_id = artifact_remote_version_id(session, snapshot.item_id, version_id, digest)
            previous = pointers.get(name, [])
            previous_comment_id = previous[-1].head_comment_id if previous else None
            if previous and previous_comment_id is None and previous[-1].comment_ids:
                previous_comment_id = previous[-1].comment_ids[0]
            metadata = {
                **_scalar_row({key: value for key, value in version.items() if key != WorkflowField.CONTENT}),
                WorkflowField.REMOTE_VERSION_ID: remote_version_id,
            }
            history_node = ArtifactHistoryNode(
                item_id=snapshot.item_id,
                name=name,
                remote_version_id=remote_version_id,
                digest=digest,
                metadata=metadata,
                previous_comment_id=previous_comment_id,
            )
            bodies = split_artifact_version_comments(
                snapshot.item_id,
                name,
                remote_version_id,
                digest,
                content,
                ordinal,
                history_node,
            )
            content_comments = [
                _io_call(session, self.io, GitHubOperation.CREATE_COMMENT, issue_number, body) for body in bodies
            ]
            created.append(
                (
                    version_id,
                    name,
                    ArtifactPointer(
                        digest=digest,
                        version=version_id,
                        remote_version_id=remote_version_id,
                        head_comment_id=content_comments[-1].database_id,
                        comment_ids=[],
                        metadata=metadata,
                    ),
                )
            )
            pointers[name] = [created[-1][2]]
        return created

    def _discover_ledger(self, session: Session, cached_issue_number: int | None) -> int | None:
        if cached_issue_number is not None:
            return cached_issue_number
        issues = _io_call(session, self.io, GitHubOperation.LIST_ISSUES)
        bot_issues = [issue for issue in issues if issue.creator == self.assignment.actor.login]
        comments_by_issue = {
            issue.number: _io_call(session, self.io, GitHubOperation.READ_COMMENTS, issue.number)
            for issue in bot_issues
        }
        try:
            ledger_issue, _entries = find_ledger(
                comments_by_issue,
                {issue.number: issue for issue in bot_issues},
                self.assignment.actor.login,
            )
        except GitHubLedgerRefused:
            raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED) from None
        if ledger_issue is None:
            return None
        save_ledger_issue(session, ledger_issue.number, ledger_issue.node_id)
        return ledger_issue.number

    def _migrate_artifact_history(
        self,
        session: Session,
        item_id: str,
        issue_number: int,
        pointers: dict[str, list[ArtifactPointer]],
    ) -> dict[str, list[ArtifactPointer]]:
        compact: dict[str, list[ArtifactPointer]] = {}
        for name, versions in pointers.items():
            if not versions:
                continue
            current = versions[-1]
            if current.head_comment_id is not None:
                compact[name] = [current]
                continue
            previous_comment_id: int | None = None
            migrated: list[ArtifactPointer] = []
            for version_ordinal, pointer in enumerate(versions, start=1):
                if pointer.head_comment_id is not None:
                    previous_comment_id = pointer.head_comment_id
                    migrated.append(pointer)
                    continue
                legacy_head = pointer.comment_ids[0] if pointer.comment_ids else pointer.version
                remote_id = pointer.remote_version_id or _LEGACY_VERSION_ID.format(item_id, legacy_head)
                metadata = {
                    **pointer.metadata,
                    WorkflowField.REMOTE_VERSION_ID: remote_id,
                    WorkflowField.VERSION_ID: pointer.version,
                }
                node = ArtifactHistoryNode(
                    item_id=item_id,
                    name=name,
                    remote_version_id=remote_id,
                    digest=pointer.digest,
                    metadata=metadata,
                    previous_comment_id=previous_comment_id,
                    legacy_comment_ids=list(pointer.comment_ids) if pointer.remote_version_id is None else [],
                )
                comment = _io_call(
                    session,
                    self.io,
                    GitHubOperation.CREATE_COMMENT,
                    issue_number,
                    render_standalone_artifact_history_comment(node, version_ordinal),
                )
                previous_comment_id = comment.database_id
                migrated.append(
                    pointer.model_copy(
                        update={
                            WorkflowField.REMOTE_VERSION_ID: remote_id,
                            WorkflowField.HEAD_COMMENT_ID: comment.database_id,
                            WorkflowField.COMMENT_IDS: [],
                            WorkflowField.METADATA: metadata,
                        }
                    )
                )
            if migrated:
                compact[name] = [migrated[-1]]
        return compact

    def _compact_old_record(
        self,
        session: Session,
        item_id: str,
        issue_number: int | None,
        record: WorkflowRecord | None,
        committed_transactions: Container[str],
    ) -> tuple[dict[str, list[ArtifactPointer]], WorkflowRecord | None]:
        if record is None:
            return {}, None
        current = effective_revision(record, committed_transactions)
        pointers = _existing_pointers(current)
        if issue_number is None:
            return pointers, WorkflowRecord(committed=current)
        compact = self._migrate_artifact_history(session, item_id, issue_number, pointers)
        revision = current.model_copy(update={WorkflowField.ARTIFACTS: compact})
        return compact, WorkflowRecord(committed=revision)

    def _mark_removed_artifacts(
        self,
        session: Session,
        item_id: str,
        issue_number: int,
        snapshot: WorkingCopyItemSnapshot,
        pointers: dict[str, list[ArtifactPointer]],
    ) -> dict[str, list[ArtifactPointer]]:
        live_names = {
            name
            for artifact in snapshot.artifacts
            if (name := _string_or_none(artifact.get(WorkflowField.NAME))) is not None
        }
        for name, versions in tuple(pointers.items()):
            if not versions:
                continue
            pointer = versions[-1]
            if name in live_names:
                pointers[name] = [pointer.model_copy(update={WorkflowField.PRESENT: True})]
                continue
            if not pointer.present:
                continue
            node = ArtifactHistoryNode(
                item_id=item_id,
                name=name,
                action=ArtifactHistoryAction.REMOVED,
                previous_comment_id=pointer.head_comment_id,
            )
            comment = _io_call(
                session,
                self.io,
                GitHubOperation.CREATE_COMMENT,
                issue_number,
                render_standalone_artifact_history_comment(node),
            )
            pointers[name] = [
                pointer.model_copy(
                    update={
                        WorkflowField.HEAD_COMMENT_ID: comment.database_id,
                        WorkflowField.PRESENT: False,
                        WorkflowField.REMOTE_VERSION_ID: None,
                        WorkflowField.METADATA: {},
                        WorkflowField.COMMENT_IDS: [],
                    }
                )
            ]
        return pointers

    def _append_state_content(
        self,
        session: Session,
        item_id: str,
        revision: int,
        content: str,
        issue_number: int,
        state_row: Mapping[str, object],
    ) -> ArtifactPointer:
        digest = hashlib.sha256(content.encode(_ENCODING)).hexdigest()
        bodies = split_state_version_comments(
            item_id,
            _STATE_NAME,
            revision,
            digest,
            content,
        )
        comments = [_io_call(session, self.io, GitHubOperation.CREATE_COMMENT, issue_number, body) for body in bodies]
        return ArtifactPointer(
            digest=digest,
            version=revision,
            comment_ids=[comment.database_id for comment in comments],
            metadata=_scalar_row({key: value for key, value in state_row.items() if key != _STATE_NAME}),
        )

    def _item_record(
        self, session: Session, issue_number: int, comment_id: int
    ) -> tuple[WorkflowRecord, GitHubComment]:
        """Read and trust the item's one record comment by its id."""
        comment = cast(
            GitHubComment, _io_call(session, self.io, GitHubOperation.READ_COMMENT, issue_number, comment_id)
        )
        trusted = self._trusted(comment)
        if trusted is None:
            raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
        try:
            record = parse_record_comment(trusted)
        except ValueError:
            raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED) from None
        return record, comment

    def _verify_item_content(self, session: Session, issue_number: int, revision: ItemRevision) -> None:
        """Refuse a write whose current revision references content without a recoverable bot version."""
        comments = cast(
            tuple[GitHubComment, ...], _io_call(session, self.io, GitHubOperation.READ_COMMENTS, issue_number)
        )
        validate_revision_content(revision, comments, self.assignment.actor.login)

    def _read_item_content(self, session: Session, issue_number: int, revision: ItemRevision, name: str) -> str:
        pointers = revision.artifacts.get(name, [])
        if not pointers:
            return _EMPTY
        pointer = latest_artifact_pointer(pointers)
        comments = _io_call(session, self.io, GitHubOperation.READ_COMMENTS, issue_number)
        try:
            history = resolve_artifact_history(
                pointer,
                revision.item_id,
                name,
                comments,
                self.assignment.actor.login,
            )
            return history[0].content
        except ValueError:
            raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED) from None

    def _write_item_record(
        self,
        session: Session,
        issue_number: int,
        comment_id: int | None,
        record: WorkflowRecord,
        record_comments: Mapping[int, GitHubComment],
        known_state_text: str | None,
        *,
        commit_point: bool,
    ) -> GitHubComment:
        effective = record.pending.revision if record.pending is not None else record.committed
        body = render_record_comment(record, self._effective_state(session, issue_number, effective, known_state_text))
        if comment_id is None:
            if commit_point:
                session.info[_COMMIT_POINT_SENT_KEY] = True
            return cast(
                GitHubComment,
                _io_call(session, self.io, GitHubOperation.CREATE_COMMENT, issue_number, body),
            )
        comment = record_comments.get(comment_id)
        if comment is None:
            comment = cast(
                GitHubComment, _io_call(session, self.io, GitHubOperation.READ_COMMENT, issue_number, comment_id)
            )
        if self._trusted(comment) is None:
            raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
        if commit_point:
            session.info[_COMMIT_POINT_SENT_KEY] = True
        return cast(
            GitHubComment,
            _io_call(session, self.io, GitHubOperation.UPDATE_COMMENT, comment.database_id, body),
        )

    def _effective_state(
        self, session: Session, issue_number: int, revision: ItemRevision, known_state_text: str | None
    ) -> Mapping[str, object]:
        if revision.state_content_pointer is not None and known_state_text is not None:
            state_text: str | None = known_state_text
        elif revision.state_content_pointer is not None:
            pointer = revision.state_content_pointer
            comments = {
                comment.database_id: comment
                for comment in _io_call(session, self.io, GitHubOperation.READ_COMMENTS, issue_number)
            }
            parts = []
            for comment_id in pointer.comment_ids:
                comment = comments.get(comment_id)
                trusted = self._trusted(comment) if comment is not None else None
                if trusted is None:
                    raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
                try:
                    parts.append(parse_content_comment(trusted))
                except ValueError:
                    raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED) from None
            try:
                state_text = join_content_comments(parts)
            except ValueError:
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED) from None
        else:
            state_text = (
                _string_or_none(revision.state.get(WorkflowField.STATE)) if revision.state is not None else None
            )
        if state_text is None:
            return {}
        try:
            values = json.loads(state_text)
        except json.JSONDecodeError:
            return {}
        return values if isinstance(values, dict) else {}

    def _ledger_reader(
        self, session: Session, ledger_issue_number: int | None
    ) -> Callable[[int | None], tuple[GitHubComment, ...]] | None:
        """Read the ledger comments after a comment id, or all of them, inside this commit."""
        if ledger_issue_number is None:
            return None

        def read(after_id: int | None) -> tuple[GitHubComment, ...]:
            if after_id is None:
                return cast(
                    tuple[GitHubComment, ...],
                    _io_call(session, self.io, GitHubOperation.READ_COMMENTS, ledger_issue_number),
                )
            return cast(
                tuple[GitHubComment, ...],
                _io_call(session, self.io, GitHubOperation.READ_COMMENTS_AFTER, ledger_issue_number, after_id),
            )

        return read

    def _trusted(self, comment: GitHubComment) -> str | None:
        return trusted_comment_body(
            author=comment.author,
            editor=comment.editor,
            body=comment.body,
            edits=comment.edit_history,
            history_complete=comment.history_complete,
            bot_login=self.assignment.actor.login,
        )

    def refresh_after_conflict(self, session: Session) -> None:
        """Refresh a stale item after SQLAlchemy rolls back the refused write."""
        if not session.info.pop(_CONFLICT_REFRESH_KEY, False):
            session.info.pop(_CONFLICT_DRIVER_KEY, None)
            return
        driver = session.info.pop(_CONFLICT_DRIVER_KEY, None)
        runner = getattr(driver, _RUN_ASYNC_METHOD, None)
        if callable(runner):

            async def refresh(_driver_connection: Any) -> None:
                await self._refresh_after_conflict()

            try:
                runner(refresh)
            except Exception as error:
                logger.warning(
                    _CONFLICT_REFRESH_FAILED,
                    reason=type(error).__name__,
                    exc_info=True,
                )
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                asyncio.run(self._refresh_after_conflict())
            except Exception as error:
                logger.warning(
                    _CONFLICT_REFRESH_FAILED,
                    reason=type(error).__name__,
                    exc_info=True,
                )
        else:
            task = loop.create_task(self._refresh_after_conflict())
            task.add_done_callback(_log_conflict_refresh_failure)

    async def _refresh_after_conflict(self) -> None:
        if self._refresh_callback is not None:
            await self._refresh_callback()


def _io_call(
    session: Session,
    io: GitHubWorkflowIO,
    operation: GitHubOperation,
    *arguments: object,
) -> Any:
    """Await the I/O loop through SQLAlchemy's async driver when inside AsyncSession.

    The call ends within the push's deadline when the push has one.
    """
    deadline: PushDeadline | None = session.info.get(_PUSH_DEADLINE_KEY)
    commit_point_sent = bool(session.info.get(_COMMIT_POINT_SENT_KEY))
    connection = session.connection().connection
    run_async = getattr(connection, _RUN_ASYNC_METHOD, None)
    if callable(run_async):
        async_method = _ASYNC_IO[operation]

        async def invoke(_driver_connection: Any) -> Any:
            if deadline is None:
                return await async_method(io, *arguments)
            return await await_within_push_deadline(
                deadline, async_method(io, *arguments), commit_point_sent=commit_point_sent
            )

        return run_async(invoke)
    if deadline is None:
        return _SYNC_IO[operation](io, *arguments)
    try:
        return io.call_sync_within(operation, max(deadline.remaining, 0.0), *arguments)
    except TimeoutError:
        raise push_deadline_expired(deadline, commit_point_sent=commit_point_sent) from None


_ASYNC_IO: dict[GitHubOperation, Callable[..., Awaitable[Any]]] = {
    GitHubOperation.OPEN_ISSUE: GitHubWorkflowIO.async_open_issue,
    GitHubOperation.UPDATE_ISSUE: GitHubWorkflowIO.async_update_issue,
    GitHubOperation.ENSURE_LABEL: GitHubWorkflowIO.async_ensure_label,
    GitHubOperation.LIST_ISSUES: GitHubWorkflowIO.async_list_issues,
    GitHubOperation.READ_COMMENTS: GitHubWorkflowIO.async_read_comments,
    GitHubOperation.READ_COMMENT: GitHubWorkflowIO.async_read_comment,
    GitHubOperation.READ_COMMENTS_AFTER: GitHubWorkflowIO.async_read_comments_after,
    GitHubOperation.CREATE_COMMENT: GitHubWorkflowIO.async_create_comment,
    GitHubOperation.UPDATE_COMMENT: GitHubWorkflowIO.async_update_comment,
}
_SYNC_IO: dict[GitHubOperation, Callable[..., Any]] = {
    GitHubOperation.OPEN_ISSUE: GitHubWorkflowIO.open_issue,
    GitHubOperation.UPDATE_ISSUE: GitHubWorkflowIO.update_issue,
    GitHubOperation.ENSURE_LABEL: GitHubWorkflowIO.ensure_label,
    GitHubOperation.LIST_ISSUES: GitHubWorkflowIO.list_issues,
    GitHubOperation.READ_COMMENTS: GitHubWorkflowIO.read_comments,
    GitHubOperation.READ_COMMENT: GitHubWorkflowIO.read_comment,
    GitHubOperation.READ_COMMENTS_AFTER: GitHubWorkflowIO.read_comments_after,
    GitHubOperation.CREATE_COMMENT: GitHubWorkflowIO.create_comment,
    GitHubOperation.UPDATE_COMMENT: GitHubWorkflowIO.update_comment,
}


def _state_text(state: Mapping[str, object] | None) -> str | None:
    """The full state text a snapshot carries, before a long state moves out to content comments."""
    if state is None:
        return None
    return _string_or_none(state.get(WorkflowField.STATE))


def _empty_revision(item_id: str) -> ItemRevision:
    return ItemRevision(item_id=item_id, revision=0, todo={})


def _existing_pointers(revision: ItemRevision | None) -> dict[str, list[ArtifactPointer]]:
    return {name: list(pointers) for name, pointers in revision.artifacts.items()} if revision is not None else {}


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    return None


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _scalar_row(row: Mapping[str, object]) -> dict[str, str | int | float | bool | None]:
    result: dict[str, str | int | float | bool | None] = {}
    for key, value in row.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            result[str(key)] = value
        else:
            raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
    return result


def _log_conflict_refresh_failure(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except Exception as error:
        logger.warning(
            _CONFLICT_REFRESH_FAILED,
            reason=type(error).__name__,
            exc_info=True,
        )
