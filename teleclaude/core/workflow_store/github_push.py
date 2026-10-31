"""Commit local working-copy mutations to the authoritative GitHub record."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import uuid
from collections.abc import Awaitable, Callable, Container, Mapping
from pathlib import Path
from typing import Any, cast

from instrukt_ai_logging import get_logger
from sqlalchemy.orm import Session

from teleclaude.core.todos_db._github_artifacts import (
    REPUBLICATION_FINALIZING_KEY,
    REQUESTED_ITEMS_KEY,
    ArtifactFact,
    clear_republication_item,
    issue_artifacts_fact,
    mark_progress_saved,
    mark_versions_saved,
    queue_artifact_deletion,
    republication_pending,
    republication_progress,
    save_committed_artifacts,
    save_issue_artifacts_fact,
    unlink_missing_versions,
)
from teleclaude.core.todos_db._ledger_knowledge import record_ledger_commits
from teleclaude.core.todos_db._working_copy import (
    WorkingCopyChanges,
    WorkingCopyField,
    WorkingCopyItemSnapshot,
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
    read_repository_bookkeeping,
    save_item_bookkeeping,
    save_ledger_issue,
)
from teleclaude.core.todos_db._write_admission import WRITE_ADMISSION_BUDGET_S
from teleclaude.core.workflow_store import github_reflection as _github_reflection
from teleclaude.core.workflow_store.github import GitHubRepositoryIdentity
from teleclaude.core.workflow_store.github_artifact_values import (
    append_entry,
    artifact_type,
    content_digest,
)
from teleclaude.core.workflow_store.github_board_io import GitHubBoardIO
from teleclaude.core.workflow_store.github_board_queue import dispatch_staged_board_items, stage_board_reflections
from teleclaude.core.workflow_store.github_conflict_refresh import ConflictRefreshScheduler
from teleclaude.core.workflow_store.github_io import (
    GitHubComment,
    GitHubWorkflowIO,
)
from teleclaude.core.workflow_store.github_io_operation import GitHubOperation
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused
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
    STATE_ARTIFACT_NAME,
    ArtifactRecord,
    ArtifactVersionEntry,
    ItemRevision,
    LedgerCommit,
    LedgerItem,
    LedgerProjectRecord,
    LedgerRecordTable,
    PendingRevision,
    WorkflowField,
    WorkflowRecord,
    WorkflowTodoStatus,
    committed_artifacts,
    effective_revision,
    make_item_revision,
    parse_record_comment,
    render_ledger_commit,
    render_record_comment,
    trusted_comment_body,
)
from teleclaude.core.workflow_store.github_reflection_queue import (
    dispatch_staged_pull_requests,
    dispatch_staged_reflections,
    stage_issue_reflections,
    stage_pull_request_reflections,
)
from teleclaude.types.github_binding import GitHubActorAssignment

_CONFLICT_REFRESH_KEY = "github_store_conflict_refresh"
_NOT_SERVED_KEY = "github_store_issue_artifacts_not_served"
_EMPTY = ""
_MAX_INLINE_STATE = 40_000
_RUN_ASYNC_METHOD = "run_async"
_LEDGER_TITLE = "TeleClaude workflow ledger"
_LEDGER_DESCRIPTION = "Project-level workflow records."
_REQUESTED_SQL = "UPDATE github_republication_pending SET requested = 1 WHERE item_id = ?"
_NOT_SERVED_SQL = "UPDATE github_repository SET issue_artifacts = ? WHERE singleton = 1"
_OUT_OF_BAND_FAILED = "github_store_out_of_band_write_failed"
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
        board: GitHubBoardIO,
    ) -> None:
        self.db_path = Path(db_path)
        self.repository = repository
        self.assignment = assignment
        self.io = io
        self.pull_requests = pull_requests
        self.board = board
        self._conflict_refresh = ConflictRefreshScheduler()

    def set_conflict_refresh(self, callback: Callable[[], Awaitable[int]]) -> None:
        """Attach the store refresh that conflict recovery schedules once a refused write's transaction has ended."""
        self._conflict_refresh.attach(callback)

    def serve_conflict_refresh_on(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the loop that serves the store's async sessions, where recovery is scheduled."""
        self._conflict_refresh.serve_store_loop(loop)

    async def stop_conflict_refresh(self) -> None:
        """Cancel an in-flight conflict refresh and wait until it has ended."""
        await self._conflict_refresh.stop()

    def before_commit(self, session: Session) -> None:
        """Push every captured row before SQLite can commit the workflow transaction."""
        changes = pending_changes(session)
        if not changes.item_ids and not changes.project_records:
            return
        # A paced push (the GitHub store switch) keeps the switch's own mutation pacing instead of the push deadline.
        session.info[_PUSH_DEADLINE_KEY] = None if self.io.paced else begin_push_deadline()
        session.info.pop(_COMMIT_POINT_SENT_KEY, None)
        try:
            self._push_changes(session, changes)
        finally:
            session.info.pop(_PUSH_DEADLINE_KEY, None)
            session.info.pop(_COMMIT_POINT_SENT_KEY, None)

    def _push_changes(self, session: Session, changes: WorkingCopyChanges) -> None:
        if issue_artifacts_fact(session) is ArtifactFact.NOT_SERVED:
            raise GitHubIORefused(GitHubIOFailure.ISSUE_ARTIFACTS_UNAVAILABLE)
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
        record_ids: list[tuple[str, int, int | None, str, int | None, ItemRevision]] = []
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
            record_ids.append((revision.item_id, issue_number, issue_id, issue_node_id, comment.database_id, revision))
            if transaction_id is not None:
                ledger_items.append(LedgerItem(issue_number=issue_number, revision=revision.revision))

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

        saved_versions = {snapshot.item_id: _version_identities(snapshot) for snapshot, *_rest in snapshots}
        for item_id, issue_number, issue_id, node_id, record_comment_id, committed_revision in record_ids:
            save_item_bookkeeping(
                session,
                item_id,
                issue_number=issue_number,
                issue_id=issue_id,
                node_id=node_id,
                record_comment_id=record_comment_id,
                revision=committed_revision.revision,
                base_revision=committed_revision.revision,
            )
            save_committed_artifacts(session, item_id, committed_artifacts(committed_revision))
            mark_versions_saved(session, item_id, saved_versions.get(item_id, ()))
            if session.info.get(REPUBLICATION_FINALIZING_KEY) == item_id:
                mark_progress_saved(session, item_id)
                clear_republication_item(session, item_id)
        if ledger_comment_id is not None:
            for table, row_id in changes.project_records:
                mark_project_record_pushed(session, table, row_id, ledger_comment_id)
        settled = stage_issue_reflections(session, reflection_rows)
        stage_pull_request_reflections(session, reflection_rows)
        stage_board_reflections(session, reflection_rows)
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
        finalizing = session.info.get(REPUBLICATION_FINALIZING_KEY) == item_id
        unlink_missing_versions(session, item_id)
        snapshot = item_snapshot(session, item_id, unpushed_only=True)
        if (
            snapshot is not None
            and _github_reflection.is_repository_work(snapshot.state)
            and republication_pending(session, item_id)
            and not finalizing
        ):
            session.info.setdefault(REQUESTED_ITEMS_KEY, set()).add(item_id)
            raise GitHubIORefused(GitHubIOFailure.AWAITING_REPUBLICATION)
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
            raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
        if (
            snapshot is None
            and old_revision is not None
            and not _github_reflection.is_repository_work(old_revision.state)
        ):
            return None
        if snapshot is not None and not _github_reflection.is_repository_work(snapshot.state):
            clear_republication_item(session, item_id)
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
                    artifact_records=old_revision.artifacts,
                    state_content_pointer=old_revision.state_content_pointer,
                )
            return snapshot, issue_number, issue_id, node_id, base_revision, revision, old_record, record_comment_id
        records = dict(old_revision.artifacts) if old_revision is not None else {}
        if snapshot is None:
            if old_revision is None or issue_number is None or node_id is None:
                return None
            todo_row = {**old_revision.todo, WorkflowField.STATUS: WorkflowTodoStatus.PURGED}
            revision = old_revision.model_copy(
                update={
                    WorkflowField.REVISION: old_revision.revision + 1,
                    WorkflowField.TODO: todo_row,
                }
            )
            snapshot = WorkingCopyItemSnapshot(
                item_id=item_id,
                todo=todo_row,
                state=old_revision.state,
                dependencies=tuple(old_revision.dependencies),
                artifacts=(),
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
        records = self._mark_removed_artifacts(session, issue_number, snapshot, records)
        records = (
            self._records_from_progress(session, item_id, records)
            if finalizing
            else self._save_unpushed_versions(session, snapshot, issue_number, records)
        )
        state = snapshot.state
        state_pointer = old_revision.state_content_pointer if old_revision is not None else None
        if state is not None:
            state_text = state.get(WorkflowField.STATE)
            if isinstance(state_text, str) and len(state_text) > _MAX_INLINE_STATE:
                state_pointer = self._save_state(session, issue_number, next_revision, state_text, state_pointer)
                state = {**state, WorkflowField.STATE: None}
            elif state_pointer is not None:
                queue_artifact_deletion(session, issue_number, state_pointer.artifact_number)
                state_pointer = None
        revision = make_item_revision(
            item_id,
            next_revision,
            snapshot.todo,
            state,
            snapshot.dependencies,
            records,
            state_content_pointer=state_pointer,
        )
        return snapshot, issue_number, issue_id, node_id, base_revision, revision, old_record, record_comment_id

    def after_commit(self, session: Session) -> None:
        """Queue issue reflections after local commit and retain failed reflections for refresh."""
        dispatch_staged_reflections(session, self.db_path, self.io)
        dispatch_staged_pull_requests(session, self.db_path, self.pull_requests)
        dispatch_staged_board_items(session, self.db_path, self.board)

    def _save_unpushed_versions(
        self,
        session: Session,
        snapshot: WorkingCopyItemSnapshot,
        issue_number: int,
        records: dict[str, ArtifactRecord],
    ) -> dict[str, ArtifactRecord]:
        """Save each version the record does not name as a version of its issue artifact, oldest first."""
        for version in snapshot.versions:
            name = _string_or_none(version.get(WorkflowField.NAME))
            content = version.get(WorkflowField.CONTENT)
            if name is None or not isinstance(content, str):
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
            record = records.get(name)
            artifact = None
            recreated = False
            if record is not None and record.present:
                try:
                    artifact = _io_call(
                        session, self.io, GitHubOperation.UPDATE_ARTIFACT, issue_number, record.artifact_number, content
                    )
                except GitHubIORefused as refused:
                    if refused.reason is not GitHubIOFailure.NOT_FOUND:
                        raise
                    recreated = True
            if artifact is None:
                artifact = _io_call(
                    session, self.io, GitHubOperation.CREATE_ARTIFACT, issue_number, artifact_type(name), name, content
                )
            records[name] = append_entry(record, artifact.number, version, recreated=recreated)
        if snapshot.versions and issue_artifacts_fact(session) is not ArtifactFact.SERVED:
            save_issue_artifacts_fact(session, ArtifactFact.SERVED)
        return records

    def _records_from_progress(
        self, session: Session, item_id: str, records: dict[str, ArtifactRecord]
    ) -> dict[str, ArtifactRecord]:
        """Name the republication's saved versions at their artifact's current address, built from its progress.

        A version saved at an address since replaced is not served, so the record leaves it out; it is still
        saved, and finalization records it as such."""
        complete = item_snapshot(session, item_id)
        if complete is None:
            raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
        saved = {row.version_id: row for row in republication_progress(session, item_id)}
        for version in complete.versions:
            version_id = _int_or_none(version.get(WorkflowField.VERSION_ID))
            name = _string_or_none(version.get(WorkflowField.NAME))
            progress = saved.get(version_id) if version_id is not None else None
            if name is None or progress is None or progress.name != name:
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
            named = records.get(name)
            records[name] = append_entry(
                named,
                progress.artifact_number,
                version,
                recreated=named is not None and named.artifact_number != progress.artifact_number,
            )
        return records

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

    def _mark_removed_artifacts(
        self,
        session: Session,
        issue_number: int,
        snapshot: WorkingCopyItemSnapshot,
        records: dict[str, ArtifactRecord],
    ) -> dict[str, ArtifactRecord]:
        """Mark each artifact the workflow removed as absent and owe the deletion of its native artifact."""
        live_names = {
            name
            for artifact in snapshot.artifacts
            if (name := _string_or_none(artifact.get(WorkflowField.NAME))) is not None
        }
        for name, record in tuple(records.items()):
            if name in live_names or not record.present:
                continue
            queue_artifact_deletion(session, issue_number, record.artifact_number)
            records[name] = ArtifactRecord(artifact_number=record.artifact_number, present=False)
        return records

    def _save_state(
        self,
        session: Session,
        issue_number: int,
        revision: int,
        content: str,
        prior: ArtifactRecord | None,
    ) -> ArtifactRecord:
        """Keep a state too long for the record as an issue artifact of its own."""
        digest = content_digest(content)
        if prior is not None and prior.entries and prior.entries[-1].digest == digest:
            return prior
        artifact = None
        if prior is not None:
            try:
                artifact = _io_call(
                    session, self.io, GitHubOperation.UPDATE_ARTIFACT, issue_number, prior.artifact_number, content
                )
            except GitHubIORefused as refused:
                if refused.reason is not GitHubIOFailure.NOT_FOUND:
                    raise
        if artifact is None:
            artifact = _io_call(
                session,
                self.io,
                GitHubOperation.CREATE_ARTIFACT,
                issue_number,
                artifact_type(STATE_ARTIFACT_NAME),
                STATE_ARTIFACT_NAME,
                content,
            )
        return ArtifactRecord(
            artifact_number=artifact.number, entries=[ArtifactVersionEntry(ordinal=revision, digest=digest)]
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
            # Only a purged item's record reaches here, with no local state; it has no live state to render.
            return {}
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
        """Finish what a refused write owes once its outermost transaction has ended.

        A conflict-refused write schedules the store refresh. A write refused for an item awaiting republication
        marks the item requested, and one refused by a repository that serves no issue artifacts records that
        fact; each is written from a thread the ended transaction does not depend on.
        """
        if session.info.pop(_CONFLICT_REFRESH_KEY, False):
            self._conflict_refresh.request()
        requested: set[str] = session.info.pop(REQUESTED_ITEMS_KEY, set())
        if requested:
            self._write_out_of_band(tuple((_REQUESTED_SQL, (item_id,)) for item_id in requested))
        if session.info.pop(_NOT_SERVED_KEY, False):
            self._write_out_of_band(((_NOT_SERVED_SQL, (ArtifactFact.NOT_SERVED.value,)),))

    def request_republication(self, item_id: str) -> None:
        """Record that a write to the item was refused, moving it to the front of republication."""
        self._write_out_of_band(((_REQUESTED_SQL, (item_id,)),))

    def _write_out_of_band(self, statements: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
        """Run bookkeeping writes on a connection of their own, bounded by the writer admission budget."""
        threading.Thread(target=self._run_out_of_band, args=(statements,), daemon=True).start()

    def _run_out_of_band(self, statements: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
        try:
            connection = sqlite3.connect(self.db_path, timeout=WRITE_ADMISSION_BUDGET_S)
            try:
                for statement, parameters in statements:
                    connection.execute(statement, parameters)
                connection.commit()
            finally:
                connection.close()
        except sqlite3.Error:
            logger.warning(_OUT_OF_BAND_FAILED, exc_info=True)


def _io_call(
    session: Session,
    io: GitHubWorkflowIO,
    operation: GitHubOperation,
    *arguments: object,
) -> Any:
    """Await the I/O loop through SQLAlchemy's async driver when inside AsyncSession.

    The call ends within the push's deadline when the push has one.
    """
    try:
        return _dispatch_io_call(session, io, operation, *arguments)
    except GitHubIORefused as refused:
        if refused.reason is GitHubIOFailure.ISSUE_ARTIFACTS_UNAVAILABLE:
            session.info[_NOT_SERVED_KEY] = True
        raise


def _dispatch_io_call(
    session: Session,
    io: GitHubWorkflowIO,
    operation: GitHubOperation,
    *arguments: object,
) -> Any:
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
    GitHubOperation.LIST_ARTIFACTS: GitHubWorkflowIO.async_list_artifacts,
    GitHubOperation.READ_ARTIFACT: GitHubWorkflowIO.async_read_artifact,
    GitHubOperation.CREATE_ARTIFACT: GitHubWorkflowIO.async_create_artifact,
    GitHubOperation.UPDATE_ARTIFACT: GitHubWorkflowIO.async_update_artifact,
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
    GitHubOperation.LIST_ARTIFACTS: GitHubWorkflowIO.list_artifacts,
    GitHubOperation.READ_ARTIFACT: GitHubWorkflowIO.read_artifact,
    GitHubOperation.CREATE_ARTIFACT: GitHubWorkflowIO.create_artifact,
    GitHubOperation.UPDATE_ARTIFACT: GitHubWorkflowIO.update_artifact,
}


def _version_identities(snapshot: WorkingCopyItemSnapshot) -> tuple[tuple[int, str], ...]:
    """The (version id, digest) of every version this push saved: the unpushed versions its snapshot carried."""
    identities: list[tuple[int, str]] = []
    for version in snapshot.versions:
        version_id = _int_or_none(version.get(WorkflowField.VERSION_ID))
        digest = _string_or_none(version.get(WorkflowField.DIGEST))
        if version_id is not None and digest is not None:
            identities.append((version_id, digest))
    return tuple(identities)


def _state_text(state: Mapping[str, object] | None) -> str | None:
    """The full state text a snapshot carries, before a long state moves out to its own issue artifact."""
    if state is None:
        return None
    return _string_or_none(state.get(WorkflowField.STATE))


def _empty_revision(item_id: str) -> ItemRevision:
    return ItemRevision(item_id=item_id, revision=0, todo={})


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
