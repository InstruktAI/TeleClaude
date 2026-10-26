"""Rebuild and refresh the disposable local copy from trusted GitHub records."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Any, cast

from instrukt_ai_logging import get_logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from teleclaude.core.todos_db._adapter import TodosDb
from teleclaude.core.todos_db._ledger_knowledge import all_ledger_commits, ledger_commits_through
from teleclaude.core.todos_db._working_copy import (
    WorkingCopyField,
    WorkingCopyItemSnapshot,
    acquire_repository_writer,
    artifact_local_version_id,
    clear_item_unverifiable,
    clear_pending_changes,
    clear_reflection_owed,
    complete_projection_repair,
    issue_relations,
    item_bookkeeping,
    item_snapshot,
    items_without_issue_id,
    mark_all_issue_reflections_owed,
    mark_item_unverifiable,
    mark_project_record_pushed,
    mark_repository_initialized,
    owed_reflections,
    purge_item_snapshot,
    read_repository_bookkeeping,
    restore_item_snapshot,
    restore_project_record,
    save_artifact_comment_ids,
    save_issue_projection_digest,
    save_item_bookkeeping,
    save_item_issue_id,
    save_ledger_issue,
    save_projection_repair_progress,
    set_refresh_watermarks,
)
from teleclaude.core.workflow_store.github import GitHubRepositoryIdentity
from teleclaude.core.workflow_store.github_io import (
    GitHubComment,
    GitHubIssue,
    GitHubWorkflowIO,
)
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused
from teleclaude.core.workflow_store.github_issue_values import issue_by_number, latest_issue_timestamp, parse_timestamp
from teleclaude.core.workflow_store.github_ledger import (
    GitHubLedgerRefused,
    find_ledger,
    parse_ledger_comment,
    trusted_body,
)
from teleclaude.core.workflow_store.github_ledger_commits import adopt_ledger_entries
from teleclaude.core.workflow_store.github_pull_request_io import GitHubPullRequestIO
from teleclaude.core.workflow_store.github_question_projection import close_resolved_questions, waiting_person_handles
from teleclaude.core.workflow_store.github_record import (
    ArtifactHistoryAction,
    ArtifactPointer,
    CommentEnvelopeAction,
    CommentEnvelopeField,
    ContentHeader,
    ItemRevision,
    LedgerCommit,
    Scalar,
    WorkflowField,
    WorkflowRecord,
    WorkflowTodoStatus,
    artifact_history_payload_line,
    effective_revision,
    has_artifact_history_marker,
    has_ledger_marker,
    has_record_marker,
    is_content_comment,
    join_content_comments,
    latest_artifact_pointer,
    parse_artifact_history_node,
    parse_content_comment,
    parse_ledger_commit,
    parse_record_comment,
    reenvelope_artifact_history_comment,
    reenvelope_ledger_comment,
    reenvelope_record_comment,
    render_enveloped_content_comment,
    resolve_artifact_history,
)
from teleclaude.core.workflow_store.github_reflection import (
    changed_projection_parts,
    is_repository_work,
    parse_projection_digests,
    platform_issue_labels,
    reflect_issue,
    serialize_projection_digests,
)
from teleclaude.core.workflow_store.github_reflection_queue import (
    owe_unwritten_pull_request,
    repair_owed_pull_requests,
)
from teleclaude.types.github_binding import GitHubActorAssignment

_LEGACY_PROJECT_ID = "legacy-{}-{}"
_LEGACY_ARTIFACT_ID = "legacy-{}-{}"
_REBUILD_COMPLETED = "github_store_rebuild_completed"
_CONTENT_UNVERIFIABLE = "content_unverifiable"
_RECORD_UNVERIFIABLE = "record_unverifiable"
_ITEM_UNVERIFIABLE = "workflow item issue #{} is unverifiable"
_ITEM_INVALID = "workflow item issue #{} is invalid"
_ITEM_MULTIPLE_RECORDS = "workflow item issue #{} has multiple records"
_ITEM_STATE_INCOMPLETE = "workflow item issue #{} state is incomplete"
_ITEM_CONTENT_INCOMPLETE = "workflow item issue #{} content is incomplete"
_ITEM_CONTENT_UNVERIFIABLE = "workflow item issue #{} content is unverifiable"
_ITEM_CONTENT_INVALID = "workflow item issue #{} content is invalid"
_ITEM_CONTENT_DISAGREES = "workflow item issue #{} content pointer disagrees"
_ITEM_ID_SQL = "SELECT item_id FROM github_item WHERE issue_number = :issue_number"
_BASE_REVISION_SQL = "SELECT base_revision FROM github_item WHERE issue_number = :issue_number"
_ISSUE_PROJECTION_VERSION = 1
_PROJECTION_REPAIRED_ISSUE = "github_store_projection_repaired_issue"
_EMPTY = ""
logger = get_logger(__name__)


class GitHubWorkflowSyncRefused(RuntimeError):
    """The authoritative repository cannot safely provide one item's state."""


class GitHubWorkflowSync:
    """Reconstruct and converge one working-copy database from platform-authored comments."""

    def __init__(
        self,
        store: TodosDb,
        repository: GitHubRepositoryIdentity,
        assignment: GitHubActorAssignment,
        io: GitHubWorkflowIO,
        pull_requests: GitHubPullRequestIO,
    ) -> None:
        self.store = store
        self.repository = repository
        self.assignment = assignment
        self.io = io
        self.pull_requests = pull_requests

    async def rebuild(self) -> None:
        """Restore every committed issue and project record into an absent database."""
        started = perf_counter()
        issues = await self.io.async_list_issues()
        comments_by_issue = {
            issue.number: await self.io.async_read_comments(issue.number)
            for issue in issues
            if issue.creator == self.assignment.actor.login
        }
        ledger_issue, ledger_entries, updates = _select_rebuild_records(
            issues, comments_by_issue, self.assignment.actor.login
        )

        resolved: list[tuple[GitHubIssue, GitHubComment, WorkingCopyItemSnapshot, ItemRevision]] = []
        for issue, _record, record_comment, revision in updates:
            snapshot = await self._snapshot_from_revision(issue.number, revision, comments_by_issue[issue.number])
            resolved.append((issue, record_comment, snapshot, revision))

        ledger_comment_id = max((comment.database_id for _entry, comment in ledger_entries), default=None)
        issue_watermark = latest_issue_timestamp(issues)

        def restore(session: Session) -> None:
            for issue, record_comment, snapshot, revision in resolved:
                restore_item_snapshot(session, snapshot)
                save_item_bookkeeping(
                    session,
                    snapshot.item_id,
                    issue_number=issue.number,
                    issue_id=issue.issue_id,
                    node_id=issue.node_id,
                    record_comment_id=record_comment.database_id,
                    revision=revision.revision,
                    base_revision=revision.revision,
                )
                _save_artifact_pointers(session, snapshot.item_id, revision)
                clear_item_unverifiable(session, snapshot.item_id)
                owe_unwritten_pull_request(session, snapshot.item_id, issue.number, snapshot)
            adopt_ledger_entries(session, ledger_entries)
            for entry, comment in ledger_entries:
                for project_record in entry.project_records:
                    remote_id = project_record.remote_record_id or _LEGACY_PROJECT_ID.format(
                        project_record.table, project_record.row_id
                    )
                    local_id = restore_project_record(session, project_record.table, project_record.data, remote_id)
                    mark_project_record_pushed(session, project_record.table, local_id, comment.database_id, remote_id)
            if ledger_issue is not None:
                save_ledger_issue(session, ledger_issue.number, ledger_issue.node_id)
            clear_pending_changes(session)
            set_refresh_watermarks(session, issue_watermark, ledger_comment_id)
            mark_repository_initialized(session)

        await self._run_async_transaction(restore)
        logger.debug(
            _REBUILD_COMPLETED,
            project=self.repository.project_path.name,
            repository_id=self.repository.repository_id,
            item_count=len(resolved),
            duration_ms=int((perf_counter() - started) * 1000),
        )

    def rebuild_sync(self) -> None:
        """Synchronous rebuild used by CLI and integrator callers."""
        started = perf_counter()
        issues = self.io.list_issues()
        comments_by_issue = {
            issue.number: self.io.read_comments(issue.number)
            for issue in issues
            if issue.creator == self.assignment.actor.login
        }
        ledger_issue, ledger_entries, updates = _select_rebuild_records(
            issues, comments_by_issue, self.assignment.actor.login
        )
        resolved: list[tuple[GitHubIssue, GitHubComment, WorkingCopyItemSnapshot, ItemRevision]] = []
        for issue, _record, record_comment, revision in updates:
            snapshot = self._snapshot_from_revision_sync(issue.number, revision, comments_by_issue[issue.number])
            resolved.append((issue, record_comment, snapshot, revision))
        ledger_comment_id = max((comment.database_id for _entry, comment in ledger_entries), default=None)
        issue_watermark = latest_issue_timestamp(issues)
        with self.store._sync_session() as session:
            with session.begin():
                for issue, record_comment, snapshot, revision in resolved:
                    restore_item_snapshot(session, snapshot)
                    save_item_bookkeeping(
                        session,
                        snapshot.item_id,
                        issue_number=issue.number,
                        issue_id=issue.issue_id,
                        node_id=issue.node_id,
                        record_comment_id=record_comment.database_id,
                        revision=revision.revision,
                        base_revision=revision.revision,
                    )
                    _save_artifact_pointers(session, snapshot.item_id, revision)
                    owe_unwritten_pull_request(session, snapshot.item_id, issue.number, snapshot)
                adopt_ledger_entries(session, ledger_entries)
                for entry, comment in ledger_entries:
                    for project_record in entry.project_records:
                        remote_id = project_record.remote_record_id or _LEGACY_PROJECT_ID.format(
                            project_record.table, project_record.row_id
                        )
                        local_id = restore_project_record(session, project_record.table, project_record.data, remote_id)
                        mark_project_record_pushed(
                            session, project_record.table, local_id, comment.database_id, remote_id
                        )
                if ledger_issue is not None:
                    save_ledger_issue(session, ledger_issue.number, ledger_issue.node_id)
                clear_pending_changes(session)
                set_refresh_watermarks(session, issue_watermark, ledger_comment_id)
                mark_repository_initialized(session)
        logger.debug(
            _REBUILD_COMPLETED,
            project=self.repository.project_path.name,
            repository_id=self.repository.repository_id,
            item_count=len(resolved),
            duration_ms=int((perf_counter() - started) * 1000),
        )

    async def refresh(self) -> int:
        """Adopt newer committed revisions, repair trusted record edits and drain reflections."""
        async with self.store._session() as read_session:
            repository_state = await read_session.run_sync(lambda session: read_repository_bookkeeping(session))
            known_commits = await read_session.run_sync(all_ledger_commits)
            known_through = await read_session.run_sync(ledger_commits_through)
        projection_repair_active = await self._repair_repository_projection_if_needed(repository_state)
        previous_issue_watermark = _str_or_none(repository_state.get(WorkflowField.ISSUE_WATERMARK))
        previous_ledger_watermark = _int_or_none(repository_state.get(WorkflowField.LEDGER_WATERMARK))
        since = parse_timestamp(previous_issue_watermark)
        issues: Sequence[GitHubIssue] = await self.io.async_list_issues(since)
        ledger_issue_number = _int_or_none(repository_state.get(WorkflowField.LEDGER_ISSUE_NUMBER))
        after_id = (
            None
            if known_through is None or previous_ledger_watermark is None
            else min(known_through, previous_ledger_watermark)
        )
        issues, ledger_issue, all_ledger = await self._read_ledger_for_refresh(issues, ledger_issue_number, after_id)
        restorable = (
            [comment for _entry, comment in all_ledger]
            if since is None or ledger_issue_number is None
            else await self.io.async_read_comments_updated_since(ledger_issue_number, since)
        )
        for comment in restorable:
            trusted = trusted_body(comment, self.assignment.actor.login)
            if trusted is not None and comment.body != trusted:
                await self.io.async_update_comment(comment.database_id, trusted)
        new_ledger = [
            (entry, comment)
            for entry, comment in all_ledger
            if previous_ledger_watermark is None or comment.database_id > previous_ledger_watermark
        ]
        committed_ids = known_commits | {entry.transaction_id for entry, _comment in all_ledger}
        restored_issue_ids = await self._restore_missing_issue_ids()
        remote_updates, unverifiable, reflection_overrides = await self._collect_remote_updates(
            issues, new_ledger, committed_ids
        )
        latest_issue_watermark = latest_issue_timestamp(issues) or previous_issue_watermark
        latest_ledger_watermark = max(
            (comment.database_id for _entry, comment in all_ledger), default=previous_ledger_watermark
        )

        applied_items: set[str] = set()
        applied_purges: set[str] = set()

        def apply(session: Session) -> None:
            for item_id, issue_id in restored_issue_ids:
                save_item_issue_id(session, item_id, issue_id)
            for item_id, reason in unverifiable:
                mark_item_unverifiable(session, item_id, reason)
            for issue, record_comment, revision, snapshot, collected_base_revision in remote_updates:
                current_bookkeeping = item_bookkeeping(session, snapshot.item_id)
                current_base_revision = (
                    _int_or_none(current_bookkeeping.get(WorkflowField.BASE_REVISION))
                    if current_bookkeeping is not None
                    else None
                )
                if current_base_revision is not None and current_base_revision > collected_base_revision:
                    continue
                applied_items.add(snapshot.item_id)
                if revision.todo.get(WorkflowField.STATUS) == WorkflowTodoStatus.PURGED:
                    applied_purges.add(snapshot.item_id)
                    save_item_bookkeeping(
                        session,
                        snapshot.item_id,
                        issue_number=issue.number,
                        issue_id=issue.issue_id,
                        node_id=issue.node_id,
                        record_comment_id=record_comment.database_id,
                        revision=revision.revision,
                        base_revision=revision.revision,
                    )
                    purge_item_snapshot(session, snapshot.item_id, str(snapshot.todo[WorkflowField.SLUG]))
                    clear_item_unverifiable(session, snapshot.item_id)
                    continue
                restore_item_snapshot(session, snapshot)
                save_item_bookkeeping(
                    session,
                    snapshot.item_id,
                    issue_number=issue.number,
                    issue_id=issue.issue_id,
                    node_id=issue.node_id,
                    record_comment_id=record_comment.database_id,
                    revision=revision.revision,
                    base_revision=revision.revision,
                )
                _save_artifact_pointers(session, snapshot.item_id, revision)
                clear_item_unverifiable(session, snapshot.item_id)
                owe_unwritten_pull_request(session, snapshot.item_id, issue.number, snapshot)
            adopt_ledger_entries(session, all_ledger)
            for entry, comment in new_ledger:
                for project_record in entry.project_records:
                    remote_id = project_record.remote_record_id or _LEGACY_PROJECT_ID.format(
                        project_record.table, project_record.row_id
                    )
                    local_id = restore_project_record(session, project_record.table, project_record.data, remote_id)
                    mark_project_record_pushed(session, project_record.table, local_id, comment.database_id, remote_id)
            if ledger_issue is not None:
                save_ledger_issue(session, ledger_issue.number, ledger_issue.node_id)
            clear_pending_changes(session)
            set_refresh_watermarks(session, latest_issue_watermark, latest_ledger_watermark)

        await self._run_async_transaction(apply)
        await close_resolved_questions(self.store)
        owed_overrides = {
            item_id: reflection_overrides[item_id] for item_id in applied_purges if item_id in reflection_overrides
        }
        blocked_items = {item_id for item_id, _reason in unverifiable}
        try:
            repaired_reflections = await self._repair_owed_reflections(owed_overrides, blocked_items)
            if repaired_reflections:

                def clear_reflections(session: Session) -> None:
                    for item_id, projection_digest in repaired_reflections.items():
                        save_issue_projection_digest(session, item_id, projection_digest)
                        clear_reflection_owed(session, item_id)

                await self._run_async_transaction(clear_reflections)
        finally:
            await repair_owed_pull_requests(self.store, self.pull_requests, blocked_items)
        if projection_repair_active:
            await self._complete_projection_repair_if_ready()
        return len(applied_items)

    async def _read_ledger_for_refresh(
        self, issues: Sequence[GitHubIssue], ledger_issue_number: int | None, after_id: int | None
    ) -> tuple[Sequence[GitHubIssue], GitHubIssue | None, list[tuple[LedgerCommit, GitHubComment]]]:
        """Read the ledger's commit entries after ``after_id``, or all of them when there is no known position."""
        ledger_issue = issue_by_number(issues, ledger_issue_number)
        discovered: list[tuple[LedgerCommit, GitHubComment]] = []
        if ledger_issue is None and ledger_issue_number is not None and after_id is not None:
            return issues, None, discovered
        if ledger_issue is None and ledger_issue_number is not None:
            issues = await self.io.async_list_issues()
            ledger_issue = issue_by_number(issues, ledger_issue_number)
        if ledger_issue is None:
            issues = await self.io.async_list_issues()
            bot_issues = [issue for issue in issues if issue.creator == self.assignment.actor.login]
            comments_by_issue = {issue.number: await self.io.async_read_comments(issue.number) for issue in bot_issues}
            ledger_issue, discovered = _find_ledger(
                comments_by_issue, {issue.number: issue for issue in bot_issues}, self.assignment.actor.login
            )
        entries = list(discovered)
        if ledger_issue is not None and not entries:
            ledger_comments = (
                await self.io.async_read_comments_after(ledger_issue.number, after_id)
                if after_id is not None
                else await self.io.async_read_comments(ledger_issue.number)
            )
            for comment in ledger_comments:
                commit = _parse_ledger_comment(comment, self.assignment.actor.login, ledger_issue.number)
                if commit is not None:
                    entries.append((commit, comment))
        return issues, ledger_issue, entries

    async def _repair_repository_projection_if_needed(self, repository_state: Mapping[str, object]) -> bool:
        version = _int_or_none(repository_state.get(WorkingCopyField.PROJECTION_VERSION)) or 0
        if version >= _ISSUE_PROJECTION_VERSION:
            return False
        cursor = _int_or_none(repository_state.get(WorkingCopyField.PROJECTION_REPAIR_AFTER_ISSUE)) or 0

        def mark_owed(session: Session) -> None:
            mark_all_issue_reflections_owed(session)

        await self._run_async_transaction(mark_owed)
        issues = sorted(
            (issue for issue in await self.io.async_list_issues() if issue.creator == self.assignment.actor.login),
            key=lambda issue: issue.number,
        )
        async with self.io.paced_mutations() as pacing:
            labels = await self.io.async_list_repository_labels()
            for label_name in labels:
                if label_name.startswith("teleclaude:"):
                    await self.io.async_delete_label(label_name)
            for label_definition in platform_issue_labels():
                await self.io.async_ensure_label(
                    label_definition.name, label_definition.color, label_definition.description
                )
            for issue in issues:
                if issue.number <= cursor:
                    continue
                comments = await self.io.async_read_comments(issue.number)
                await self._backfill_issue_comments(issue, comments)
                await pacing.wait_between_items()

                def mark_complete(session: Session, number: int = issue.number) -> None:
                    save_projection_repair_progress(session, number)

                await self._run_async_transaction(mark_complete)
                logger.debug(
                    _PROJECTION_REPAIRED_ISSUE,
                    issue_number=issue.number,
                    comment_count=len(comments),
                )
        return True

    async def _backfill_issue_comments(self, issue: GitHubIssue, comments: Sequence[GitHubComment]) -> None:
        bot_login = self.assignment.actor.login
        record: WorkflowRecord | None = None
        if any(
            (trusted := trusted_body(comment, bot_login)) is not None and has_record_marker(trusted)
            for comment in comments
        ):
            record, _record_comment = _find_record(comments, bot_login, issue.number)
        artifact_ordinals: Mapping[tuple[str, str], int] = {}
        if record is not None:
            revision = record.pending.revision if record.pending is not None else record.committed
            artifact_ordinals = _artifact_version_ordinals(revision, comments, bot_login)
        for comment in comments:
            if comment.author != bot_login:
                continue
            trusted = trusted_body(comment, bot_login)
            if trusted is None:
                continue
            replacement = trusted
            if has_record_marker(trusted):
                record = parse_record_comment(trusted)
                revision = record.pending.revision if record.pending is not None else record.committed
                snapshot = _snapshot_from_revision(revision, comments, bot_login, issue.number)
                replacement = reenvelope_record_comment(trusted, record, _effective_state_mapping(snapshot))
            elif has_ledger_marker(trusted):
                replacement = reenvelope_ledger_comment(trusted, parse_ledger_commit(trusted))
            elif is_content_comment(trusted):
                header, content = parse_content_comment(trusted)
                fields: tuple[tuple[CommentEnvelopeField, Scalar], ...]
                if header.name == WorkflowField.STATE:
                    fields = (
                        (CommentEnvelopeField.ACTION, CommentEnvelopeAction.RECORD),
                        (CommentEnvelopeField.REVISION, header.version),
                    )
                else:
                    ordinal = artifact_ordinals.get((header.name, str(header.version)))
                    if ordinal is None:
                        raise GitHubWorkflowSyncRefused(_ITEM_CONTENT_INCOMPLETE.format(issue.number))
                    fields = (
                        (CommentEnvelopeField.ACTION, CommentEnvelopeAction.ARTIFACT),
                        (CommentEnvelopeField.NAME, header.name),
                        (CommentEnvelopeField.VERSION, ordinal),
                    )
                history_payload = (
                    artifact_history_payload_line(trusted) if has_artifact_history_marker(trusted) else None
                )
                replacement = render_enveloped_content_comment(
                    header, content, fields, history_payload_line=history_payload
                )
            elif has_artifact_history_marker(trusted):
                node = parse_artifact_history_node(trusted)
                if node.action is ArtifactHistoryAction.REMOVED:
                    fields = (
                        (CommentEnvelopeField.ACTION, CommentEnvelopeAction.ARTIFACT_REMOVED),
                        (CommentEnvelopeField.NAME, node.name),
                    )
                else:
                    ordinal = artifact_ordinals.get(
                        (node.name, str(node.remote_version_id or node.metadata.get(WorkflowField.VERSION_ID)))
                    )
                    if ordinal is None:
                        raise GitHubWorkflowSyncRefused(_ITEM_CONTENT_INCOMPLETE.format(issue.number))
                    fields = (
                        (CommentEnvelopeField.ACTION, CommentEnvelopeAction.ARTIFACT),
                        (CommentEnvelopeField.NAME, node.name),
                        (CommentEnvelopeField.VERSION, ordinal),
                    )
                replacement = reenvelope_artifact_history_comment(trusted, fields)
            if replacement != comment.body:
                await self.io.async_update_comment(comment.database_id, replacement)

    async def _complete_projection_repair_if_ready(self) -> None:
        def complete_if_ready(session: Session) -> None:
            owed = owed_reflections(session)
            outstanding_issue_reflections = any(
                (bookkeeping := item_bookkeeping(session, item_id)) is not None
                and bookkeeping.get(WorkflowField.ISSUE_NUMBER) is not None
                for item_id in owed
            )
            if not outstanding_issue_reflections:
                complete_projection_repair(session, _ISSUE_PROJECTION_VERSION)

        await self._run_async_transaction(complete_if_ready)

    async def _collect_remote_updates(
        self,
        issues: Sequence[GitHubIssue],
        ledger_entries: Sequence[tuple[LedgerCommit, GitHubComment]],
        committed_transactions: set[str],
    ) -> tuple[
        list[tuple[GitHubIssue, GitHubComment, ItemRevision, WorkingCopyItemSnapshot, int]],
        list[tuple[str, str]],
        dict[str, tuple[int, WorkingCopyItemSnapshot]],
    ]:
        candidate_numbers = {issue.number for issue in issues if issue.creator == self.assignment.actor.login}
        candidate_numbers.update(item.issue_number for entry, _comment in ledger_entries for item in entry.items)
        issue_by_number = {issue.number: issue for issue in issues}
        updates: list[tuple[GitHubIssue, GitHubComment, ItemRevision, WorkingCopyItemSnapshot, int]] = []
        unverifiable: list[tuple[str, str]] = []
        reflection_overrides: dict[str, tuple[int, WorkingCopyItemSnapshot]] = {}
        for issue_number in sorted(candidate_numbers):
            issue = issue_by_number.get(issue_number)
            if issue is None:
                issue = next((item for item in await self.io.async_list_issues() if item.number == issue_number), None)
            if issue is None:
                continue
            comments = await self.io.async_read_comments(issue_number)
            record, record_comment, reason = _find_record_for_refresh(
                comments, self.assignment.actor.login, issue_number
            )
            if reason is not None:
                item_id = await self._item_id_for_issue(issue_number)
                if item_id is not None:
                    unverifiable.append((item_id, reason))
                continue
            if record is None or record_comment is None:
                continue
            revision = effective_revision(record, committed_transactions)
            if not is_repository_work(revision.state):
                continue
            trusted = trusted_body(record_comment, self.assignment.actor.login)
            if trusted is not None and record_comment.body != trusted:
                await self.io.async_update_comment(record_comment.database_id, trusted)
            await self._repair_history_bodies(revision, comments)
            base_revision = await self._base_revision_for_issue(issue_number)
            try:
                snapshot = await self._snapshot_from_revision(issue_number, revision, comments)
            except GitHubWorkflowSyncRefused:
                unverifiable.append((revision.item_id, _CONTENT_UNVERIFIABLE))
                continue
            if revision.todo.get(WorkflowField.STATUS) == WorkflowTodoStatus.PURGED:
                reflection_overrides[revision.item_id] = (issue.number, snapshot)
            if revision.revision <= base_revision:
                continue
            updates.append((issue, record_comment, revision, snapshot, base_revision))
        return updates, unverifiable, reflection_overrides

    async def _restore_missing_issue_ids(self) -> list[tuple[str, int]]:
        """Backfill REST issue IDs on working-copy rows written before relation projection."""
        async with self.store._session() as session:
            missing = await session.run_sync(items_without_issue_id)
        restored: list[tuple[str, int]] = []
        for item_id, issue_number in missing:
            try:
                issue = await self.io.async_get_issue(issue_number)
            except GitHubIORefused as error:
                if error.reason is GitHubIOFailure.NOT_FOUND:
                    continue
                raise
            restored.append((item_id, issue.issue_id))
        return restored

    async def _repair_history_bodies(self, revision: ItemRevision, comments: Sequence[GitHubComment]) -> None:
        by_id = {comment.database_id: comment for comment in comments}
        pointers = [(name, pointer) for name, versions in revision.artifacts.items() for pointer in versions]
        if revision.state_content_pointer is not None:
            pointers.append((WorkflowField.STATE, revision.state_content_pointer))
        for name, pointer in pointers:
            try:
                history = resolve_artifact_history(
                    pointer, revision.item_id, name, comments, self.assignment.actor.login
                )
            except ValueError:
                continue
            for version in history:
                comment_ids = set(version.content_comment_ids)
                if pointer.head_comment_id is not None and version.head_comment_id is not None:
                    comment_ids.add(version.head_comment_id)
                for comment_id in comment_ids:
                    comment = by_id.get(comment_id)
                    trusted = trusted_body(comment, self.assignment.actor.login) if comment is not None else None
                    if trusted is not None and comment is not None and comment.body != trusted:
                        await self.io.async_update_comment(comment.database_id, trusted)

    async def _repair_owed_reflections(
        self,
        overrides: Mapping[str, tuple[int, WorkingCopyItemSnapshot]],
        blocked_items: set[str],
    ) -> dict[str, str]:
        async with self.store._session() as read_session:
            owed = await read_session.run_sync(lambda session: owed_reflections(session))
            completed: dict[str, str] = {}
            for item_id in owed:
                if item_id in blocked_items:
                    continue
                override = overrides.get(item_id)
                if override is not None:
                    issue_number, snapshot = override

                    def read_override_bookkeeping(
                        session: Session, target: str = item_id
                    ) -> Mapping[str, object] | None:
                        return item_bookkeeping(session, target)

                    bookkeeping = await read_session.run_sync(read_override_bookkeeping)
                else:

                    def read_snapshot(session: Session, target: str = item_id) -> WorkingCopyItemSnapshot | None:
                        return item_snapshot(session, target)

                    def read_bookkeeping(session: Session, target: str = item_id) -> Mapping[str, object] | None:
                        return item_bookkeeping(session, target)

                    snapshot = await read_session.run_sync(read_snapshot)
                    bookkeeping = await read_session.run_sync(read_bookkeeping)
                    if snapshot is None or bookkeeping is None:
                        continue
                    issue_number = _int_or_none(bookkeeping.get(WorkflowField.ISSUE_NUMBER))
                    if issue_number is None:
                        continue
                if bookkeeping is None:
                    continue
                issue_id = _int_or_none(bookkeeping.get(WorkingCopyField.ISSUE_ID))
                if issue_id is None:
                    continue
                relations = await read_session.run_sync(issue_relations, snapshot, {})

                reflection = reflect_issue(
                    snapshot,
                    parent_issue_number=relations.parent_issue_number,
                    parent_issue_id=relations.parent_issue_id,
                    blocked_by_issue_ids=relations.blocked_by_issue_ids,
                    waiting_assignees=await read_session.run_sync(waiting_person_handles, item_id, snapshot),
                )
                previous = parse_projection_digests(bookkeeping.get(WorkingCopyField.PROJECTION_DIGEST))
                changed = changed_projection_parts(reflection, previous)
                await self.io.async_reflect_issue(issue_number, issue_id, reflection, changed)
                completed[item_id] = serialize_projection_digests(reflection.projection_digests)
        return completed

    async def _item_id_for_issue(self, issue_number: int) -> str | None:
        async with self.store._session() as session:
            row = await session.run_sync(
                lambda sync_session: sync_session.execute(
                    text(_ITEM_ID_SQL),
                    {WorkflowField.ISSUE_NUMBER: issue_number},
                ).first()
            )
        return str(row[0]) if row is not None else None

    async def _base_revision_for_issue(self, issue_number: int) -> int:
        async with self.store._session() as session:
            value = await session.run_sync(
                lambda sync_session: sync_session.execute(
                    text(_BASE_REVISION_SQL),
                    {WorkflowField.ISSUE_NUMBER: issue_number},
                ).scalar_one_or_none()
            )
        return int(value) if isinstance(value, int) else 0

    async def _run_async_transaction(self, operation: Any) -> None:
        async with self.store._session() as session:
            async with session.begin():
                await session.run_sync(acquire_repository_writer)
                await session.run_sync(operation)

    async def _snapshot_from_revision(
        self, issue_number: int, revision: ItemRevision, comments: Sequence[GitHubComment]
    ) -> WorkingCopyItemSnapshot:
        return _snapshot_from_revision(revision, comments, self.assignment.actor.login, issue_number)

    def _snapshot_from_revision_sync(
        self, issue_number: int, revision: ItemRevision, comments: Sequence[GitHubComment]
    ) -> WorkingCopyItemSnapshot:
        return _snapshot_from_revision(revision, comments, self.assignment.actor.login, issue_number)


def _find_ledger(
    comments_by_issue: Mapping[int, Sequence[GitHubComment]],
    issues_by_number: Mapping[int, GitHubIssue],
    bot_login: str,
) -> tuple[GitHubIssue | None, list[tuple[LedgerCommit, GitHubComment]]]:
    try:
        return find_ledger(comments_by_issue, issues_by_number, bot_login)
    except GitHubLedgerRefused as error:
        raise GitHubWorkflowSyncRefused(str(error)) from error


def _select_rebuild_records(
    issues: Sequence[GitHubIssue],
    comments_by_issue: Mapping[int, Sequence[GitHubComment]],
    bot_login: str,
) -> tuple[
    GitHubIssue | None,
    list[tuple[LedgerCommit, GitHubComment]],
    list[tuple[GitHubIssue, WorkflowRecord, GitHubComment, ItemRevision]],
]:
    """Select the committed issue revisions shared by both rebuild entry points."""
    ledger_issue, ledger_entries = _find_ledger(comments_by_issue, {issue.number: issue for issue in issues}, bot_login)
    committed_ids = {entry.transaction_id for entry, _comment in ledger_entries}
    updates: list[tuple[GitHubIssue, WorkflowRecord, GitHubComment, ItemRevision]] = []
    for issue in issues:
        if issue.creator != bot_login:
            continue
        record, record_comment = _find_record(comments_by_issue.get(issue.number, ()), bot_login, issue.number)
        if record is None or record_comment is None:
            continue
        revision = effective_revision(record, committed_ids)
        if not is_repository_work(revision.state):
            continue
        if revision.todo.get(WorkflowField.STATUS) == WorkflowTodoStatus.PURGED:
            continue
        updates.append((issue, record, record_comment, revision))
    return ledger_issue, ledger_entries, updates


def _parse_ledger_comment(comment: GitHubComment, bot_login: str, issue_number: int) -> LedgerCommit | None:
    try:
        return parse_ledger_comment(comment, bot_login, issue_number)
    except GitHubLedgerRefused as error:
        raise GitHubWorkflowSyncRefused(str(error)) from error


def _find_record(
    comments: Sequence[GitHubComment], bot_login: str, issue_number: int
) -> tuple[WorkflowRecord | None, GitHubComment | None]:
    matches: list[tuple[WorkflowRecord, GitHubComment]] = []
    unverifiable_platform_comment = False
    for comment in comments:
        trusted = trusted_body(comment, bot_login)
        if trusted is None:
            if comment.author == bot_login and not is_content_comment(comment.body) and has_record_marker(comment.body):
                raise GitHubWorkflowSyncRefused(_ITEM_UNVERIFIABLE.format(issue_number))
            if comment.author == bot_login and not is_content_comment(comment.body):
                unverifiable_platform_comment = True
            continue
        if is_content_comment(trusted) or not has_record_marker(trusted):
            continue
        try:
            matches.append((parse_record_comment(trusted), comment))
        except ValueError:
            raise GitHubWorkflowSyncRefused(_ITEM_INVALID.format(issue_number)) from None
    if len(matches) > 1:
        raise GitHubWorkflowSyncRefused(_ITEM_MULTIPLE_RECORDS.format(issue_number))
    if not matches and unverifiable_platform_comment:
        raise GitHubWorkflowSyncRefused(_ITEM_UNVERIFIABLE.format(issue_number))
    return matches[0] if matches else (None, None)


def _find_record_for_refresh(
    comments: Sequence[GitHubComment], bot_login: str, issue_number: int
) -> tuple[WorkflowRecord | None, GitHubComment | None, str | None]:
    try:
        record, comment = _find_record(comments, bot_login, issue_number)
    except GitHubWorkflowSyncRefused:
        return None, None, _RECORD_UNVERIFIABLE
    return record, comment, None


def _snapshot_from_revision(
    revision: ItemRevision,
    comments: Sequence[GitHubComment],
    bot_login: str,
    issue_number: int,
) -> WorkingCopyItemSnapshot:
    todo = dict(revision.todo)
    state = dict(revision.state) if revision.state is not None else None
    if revision.state_content_pointer is not None:
        state_content = _content_from_pointer(
            revision.state_content_pointer,
            revision.item_id,
            WorkflowField.STATE,
            comments,
            bot_login,
            issue_number,
        )
        if state is None:
            state = dict(revision.state_content_pointer.metadata)
        state[WorkflowField.STATE] = state_content
    if state is not None:
        state.setdefault(WorkflowField.ID, revision.item_id)
        state.setdefault(WorkflowField.SLUG, str(todo.get(WorkflowField.SLUG, _EMPTY)))
        if state.get(WorkflowField.STATE) is None and revision.state_content_pointer is None:
            raise GitHubWorkflowSyncRefused(_ITEM_STATE_INCOMPLETE.format(issue_number))
    versions: list[Mapping[str, object]] = []
    artifacts: list[Mapping[str, object]] = []
    for name, pointers in revision.artifacts.items():
        for pointer in pointers:
            try:
                history = resolve_artifact_history(pointer, revision.item_id, name, comments, bot_login)
            except ValueError as error:
                raise GitHubWorkflowSyncRefused(_ITEM_CONTENT_INCOMPLETE.format(issue_number)) from error
            recent_versions = []
            for resolved in history:
                if resolved.action is ArtifactHistoryAction.REMOVED:
                    break
                recent_versions.append(resolved)
            for resolved in reversed(recent_versions):
                historical = resolved.pointer
                metadata = dict(historical.metadata)
                metadata.setdefault(WorkflowField.ID, revision.item_id)
                metadata.setdefault(WorkflowField.SLUG, str(todo.get(WorkflowField.SLUG, _EMPTY)))
                metadata.setdefault(WorkflowField.NAME, name)
                metadata.setdefault(WorkflowField.VERSION_ID, historical.version)
                metadata[WorkflowField.REMOTE_VERSION_ID] = historical.remote_version_id or _LEGACY_ARTIFACT_ID.format(
                    revision.item_id, historical.version
                )
                metadata.setdefault(WorkflowField.DIGEST, historical.digest)
                metadata[WorkflowField.CONTENT] = resolved.content
                versions.append(metadata)
        if pointers:
            pointer = latest_artifact_pointer(pointers)
            try:
                current = resolve_artifact_history(pointer, revision.item_id, name, comments, bot_login)[0]
            except (IndexError, ValueError) as error:
                raise GitHubWorkflowSyncRefused(_ITEM_CONTENT_INCOMPLETE.format(issue_number)) from error
            if pointer.present:
                if current.action is not ArtifactHistoryAction.VERSION:
                    raise GitHubWorkflowSyncRefused(_ITEM_CONTENT_INCOMPLETE.format(issue_number))
                metadata = dict(current.pointer.metadata)
                artifacts.append(
                    {
                        WorkflowField.ID: revision.item_id,
                        WorkflowField.SLUG: str(todo.get(WorkflowField.SLUG, _EMPTY)),
                        WorkflowField.NAME: name,
                        WorkflowField.CONTENT: current.content,
                        WorkflowField.DIGEST: pointer.digest,
                        WorkflowField.UPDATED_BY: metadata.get(WorkflowField.UPDATED_BY),
                        WorkflowField.UPDATED_AT: metadata.get(WorkflowField.CREATED_AT),
                    }
                )
    dependencies = tuple(dict(edge) for edge in revision.dependencies)
    return WorkingCopyItemSnapshot(
        item_id=revision.item_id,
        todo=todo,
        state=state,
        dependencies=dependencies,
        artifacts=tuple(artifacts),
        versions=tuple(versions),
    )


def _content_from_pointer(
    pointer: ArtifactPointer,
    item_id: str,
    name: str,
    comments: Sequence[GitHubComment],
    bot_login: str,
    issue_number: int,
) -> str:
    by_id = {comment.database_id: comment for comment in comments}
    parts: list[tuple[ContentHeader, str]] = []
    for comment_id in pointer.comment_ids:
        comment = by_id.get(comment_id)
        if comment is None:
            raise GitHubWorkflowSyncRefused(_ITEM_CONTENT_INCOMPLETE.format(issue_number))
        trusted = trusted_body(comment, bot_login)
        if trusted is None:
            raise GitHubWorkflowSyncRefused(_ITEM_CONTENT_UNVERIFIABLE.format(issue_number))
        try:
            header, content = parse_content_comment(trusted)
        except ValueError:
            raise GitHubWorkflowSyncRefused(_ITEM_CONTENT_INVALID.format(issue_number)) from None
        if (
            header.item_id != item_id
            or header.name != name
            or header.version != (pointer.remote_version_id or pointer.version)
            or header.digest != pointer.digest
        ):
            raise GitHubWorkflowSyncRefused(_ITEM_CONTENT_DISAGREES.format(issue_number))
        parts.append((header, content))
    try:
        return join_content_comments(parts)
    except ValueError:
        raise GitHubWorkflowSyncRefused(_ITEM_CONTENT_INCOMPLETE.format(issue_number)) from None


def _effective_state_mapping(snapshot: WorkingCopyItemSnapshot) -> Mapping[str, object]:
    if snapshot.state is None:
        return {}
    value = snapshot.state.get(WorkflowField.STATE)
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return cast(Mapping[str, object], parsed) if isinstance(parsed, dict) else {}


def _artifact_version_ordinals(
    revision: ItemRevision,
    comments: Sequence[GitHubComment],
    bot_login: str,
) -> Mapping[tuple[str, str], int]:
    ordinals: dict[tuple[str, str], int] = {}
    for name, pointers in revision.artifacts.items():
        if not pointers:
            continue
        history = resolve_artifact_history(
            latest_artifact_pointer(pointers), revision.item_id, name, comments, bot_login
        )
        seen: set[str] = set()
        ordinal = 0
        for version in reversed(history):
            if version.action is not ArtifactHistoryAction.VERSION:
                continue
            pointer = version.pointer
            identity = pointer.remote_version_id or str(pointer.version)
            if identity in seen:
                continue
            seen.add(identity)
            ordinal += 1
            for value in (pointer.remote_version_id, pointer.version, pointer.metadata.get(WorkflowField.VERSION_ID)):
                if value is not None:
                    ordinals[(name, str(value))] = ordinal
    return ordinals


def _save_artifact_pointers(session: Session, item_id: str, revision: ItemRevision) -> None:
    for pointers in revision.artifacts.values():
        for pointer in pointers:
            remote_id = pointer.remote_version_id or _LEGACY_ARTIFACT_ID.format(item_id, pointer.version)
            local_id = artifact_local_version_id(session, item_id, remote_id)
            if local_id is not None:
                save_artifact_comment_ids(session, item_id, local_id, pointer.comment_ids, remote_id, pointer.digest)


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None
