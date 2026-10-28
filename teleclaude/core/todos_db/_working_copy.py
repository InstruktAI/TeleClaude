"""Working-copy capture and typed snapshots for the local workflow implementation."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

_EMPTY = ""
_ARTIFACT_DIGEST_REQUIRED = "Restored artifact version is missing its digest"


class WorkingCopyField(StrEnum):
    """Closed set of SQLite fields and named parameters used by this adapter."""

    ID = "id"
    ITEM_ID = "item_id"
    ISSUE_NUMBER = "issue_number"
    ISSUE_ID = "issue_id"
    NODE_ID = "node_id"
    RECORD_COMMENT_ID = "record_comment_id"
    REVISION = "revision"
    BASE_REVISION = "base_revision"
    PROJECTION_DIGEST = "projection_digest"
    TABLE_NAME = "table_name"
    ROW_ID = "row_id"
    REMOTE_VERSION_ID = "remote_version_id"
    REMOTE_RECORD_ID = "remote_record_id"
    COMMENT_ID = "comment_id"
    COMMENT_IDS = "comment_ids"
    REMOTE_ID = "remote_id"
    VERSION_ID = "version_id"
    DIGEST = "digest"
    SLUG = "slug"
    STATUS = "status"
    GROUP_ID = "group_id"
    DEPENDS_ON = "depends_on"
    NAME = "name"
    CONTENT = "content"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    UPDATED_BY = "updated_by"
    STATE = "state"
    REASON = "reason"
    INITIALIZED = "initialized"
    NUMBER = "number"
    LEDGER_NODE_ID = "ledger_node_id"
    ISSUE_WATERMARK = "issue_watermark"
    LEDGER_WATERMARK = "ledger_watermark"
    PROJECTION_VERSION = "projection_version"
    PROJECTION_REPAIR_AFTER_ISSUE = "projection_repair_after_issue"
    SUPPRESSED = "suppressed"
    SINGLETON = "singleton"


class WorkingCopySql(StrEnum):
    """Named SQL statements used by working-copy capture and restoration."""

    PENDING_ITEMS = "SELECT item_id FROM working_copy_pending_item ORDER BY item_id"
    DEFER_FOREIGN_KEYS = "PRAGMA defer_foreign_keys = ON"
    PENDING_PROJECTS = "SELECT table_name, row_id FROM working_copy_pending_project ORDER BY table_name, row_id"
    MOVE_SET = (
        "WITH RECURSIVE move_rows(id, group_id, status, depth) AS ("
        " SELECT id, group_id, status, 0 FROM todo WHERE status IN ('active', 'icebox')"
        " UNION ALL"
        " SELECT parent.id, parent.group_id, parent.status, child.depth + 1"
        " FROM todo AS parent JOIN move_rows AS child ON parent.id = child.group_id"
        " WHERE parent.status = 'holder'"
        ")"
        " SELECT DISTINCT id, group_id, status, depth FROM move_rows"
        " ORDER BY depth DESC, id"
    )
    HELD_ITEM_IDS = "SELECT CAST(id AS TEXT) FROM todo ORDER BY id"
    PROJECT_IDS = "SELECT id FROM {} ORDER BY id"
    TODO_BY_ID = "SELECT * FROM todo WHERE id = :item_id"
    TODO_BY_SLUG = "SELECT id, status FROM todo WHERE slug = :slug"
    DEPENDENTS_BY_SLUG = (
        "SELECT DISTINCT CAST(t.id AS TEXT) FROM todo_deps AS d JOIN todo AS t ON t.slug = d.slug "
        "WHERE d.depends_on = :slug"
    )
    GROUP_MEMBERS_BY_ID = "SELECT CAST(id AS TEXT) FROM todo WHERE group_id = :group_id"
    STATE_BY_ID = "SELECT * FROM todo_state WHERE id = :item_id"
    DEPENDENCIES_BY_ITEM = (
        "SELECT d.slug, d.depends_on FROM todo_deps AS d JOIN todo AS t ON t.slug = d.slug WHERE t.id = :item_id"
    )
    ARTIFACTS_BY_ITEM = "SELECT * FROM todo_artifacts WHERE id = :item_id ORDER BY name"
    VERSIONS_BY_ITEM = "SELECT * FROM todo_artifact_versions WHERE id = :item_id"
    UNPUSHED_VERSION_FILTER = (
        " AND NOT EXISTS (SELECT 1 FROM github_artifact_content AS pushed "
        "WHERE pushed.item_id = todo_artifact_versions.id "
        "AND pushed.version_id = todo_artifact_versions.version_id "
        "AND pushed.digest = todo_artifact_versions.digest)"
    )
    VERSION_ORDER = " ORDER BY version_id"
    PROJECT_BY_ID = "SELECT * FROM {} WHERE id = :row_id"
    SUPPRESS_CAPTURE = "UPDATE working_copy_capture_control SET suppressed = 1 WHERE singleton = 1"
    RELEASE_CAPTURE = "UPDATE working_copy_capture_control SET suppressed = 0 WHERE singleton = 1"
    ACQUIRE_REPOSITORY_WRITER = "UPDATE github_repository SET singleton = singleton WHERE singleton = 1"
    DELETE_ITEM_ROW = "DELETE FROM {} WHERE id = :item_id"
    DELETE_DEPENDENCIES = "DELETE FROM todo_deps WHERE slug = :slug"
    DELETE_DEPENDENCIES_FOR_ITEM = (
        "DELETE FROM todo_deps WHERE slug = :slug AND NOT EXISTS "
        "(SELECT 1 FROM todo WHERE id != :item_id AND slug = :slug)"
    )
    INSERT_DEPENDENCY = "INSERT INTO todo_deps(slug, depends_on) VALUES (:slug, :depends_on)"
    LAST_INSERT_ID = "SELECT last_insert_rowid()"
    CLEAR_PENDING_ITEMS = "DELETE FROM working_copy_pending_item"
    CLEAR_PENDING_PROJECTS = "DELETE FROM working_copy_pending_project"
    CLEAR_ARTIFACT_MAPS = "DELETE FROM github_artifact_content WHERE item_id = :item_id"
    ITEM_BOOKKEEPING = "SELECT * FROM github_item WHERE item_id = :item_id"
    ITEMS_WITHOUT_ISSUE_ID = (
        "SELECT item_id, issue_number FROM github_item WHERE issue_number IS NOT NULL AND issue_id IS NULL"
    )
    SAVE_PROJECTION_DIGEST = "UPDATE github_item SET projection_digest = :projection_digest WHERE item_id = :item_id"
    SAVE_ISSUE_ID = "UPDATE github_item SET issue_id = :issue_id WHERE item_id = :item_id"
    SAVE_ITEM_BOOKKEEPING = (
        "INSERT INTO github_item(item_id, issue_number, issue_id, node_id, record_comment_id, revision, base_revision, "
        "projection_digest) VALUES (:item_id, :issue_number, :issue_id, :node_id, :record_comment_id, :revision, "
        ":base_revision, :projection_digest) ON CONFLICT(item_id) DO UPDATE SET "
        "issue_number = excluded.issue_number, issue_id = COALESCE(excluded.issue_id, github_item.issue_id), "
        "node_id = excluded.node_id, "
        "record_comment_id = excluded.record_comment_id, revision = excluded.revision, "
        "base_revision = excluded.base_revision, "
        "projection_digest = COALESCE(excluded.projection_digest, github_item.projection_digest)"
    )
    PRUNE_ARTIFACT_MAPS = (
        "DELETE FROM github_artifact_content WHERE item_id = :item_id AND NOT EXISTS ("
        "SELECT 1 FROM todo_artifact_versions WHERE id = :item_id "
        "AND version_id = github_artifact_content.version_id)"
    )
    ARTIFACT_MAP_BY_LOCAL_ID = (
        "SELECT remote_version_id, digest FROM github_artifact_content "
        "WHERE item_id = :item_id AND version_id = :version_id"
    )
    SAVE_ARTIFACT_MAP = (
        "INSERT INTO github_artifact_content(item_id, version_id, remote_version_id, digest, comment_ids) "
        "VALUES (:item_id, :version_id, :remote_version_id, :digest, :comment_ids) "
        "ON CONFLICT(item_id, version_id) DO UPDATE SET remote_version_id = excluded.remote_version_id, "
        "digest = excluded.digest, comment_ids = excluded.comment_ids"
    )
    ARTIFACT_LOCAL_ID = (
        "SELECT version_id FROM github_artifact_content WHERE item_id = :item_id AND remote_version_id = :remote_id"
    )
    REPOSITORY_BOOKKEEPING = "SELECT * FROM github_repository WHERE singleton = 1"
    REPOSITORY_INITIALIZED = "SELECT initialized FROM github_repository WHERE singleton = 1"
    MARK_REPOSITORY_INITIALIZED = "UPDATE github_repository SET initialized = 1 WHERE singleton = 1"
    MARK_ALL_ISSUE_REFLECTIONS_OWED = (
        "INSERT OR IGNORE INTO github_owed_reflection(item_id) "
        "SELECT item_id FROM github_item WHERE issue_number IS NOT NULL"
    )
    SAVE_PROJECTION_REPAIR_PROGRESS = (
        "UPDATE github_repository SET projection_repair_after_issue = :number WHERE singleton = 1"
    )
    COMPLETE_PROJECTION_REPAIR = (
        "UPDATE github_repository SET projection_version = :projection_version, projection_repair_after_issue = 0 "
        "WHERE singleton = 1"
    )
    SAVE_LEDGER_ISSUE = (
        "UPDATE github_repository SET ledger_issue_number = :number, ledger_node_id = :node_id WHERE singleton = 1"
    )
    PROJECT_MAP_BY_LOCAL_ID = (
        "SELECT remote_record_id FROM github_project_record WHERE table_name = :table_name AND row_id = :row_id"
    )
    SAVE_PROJECT_MAP = (
        "INSERT INTO github_project_record(table_name, row_id, remote_record_id, comment_id) "
        "VALUES (:table_name, :row_id, :remote_id, :comment_id) "
        "ON CONFLICT(table_name, row_id) DO UPDATE SET remote_record_id = excluded.remote_record_id"
    )
    MARK_PROJECT_MAP = (
        "INSERT INTO github_project_record(table_name, row_id, remote_record_id, comment_id) "
        "VALUES (:table_name, :row_id, :remote_record_id, :comment_id) "
        "ON CONFLICT(table_name, row_id) DO UPDATE SET remote_record_id = COALESCE(excluded.remote_record_id, "
        "github_project_record.remote_record_id), comment_id = excluded.comment_id"
    )
    PROJECT_MAP_BY_REMOTE_ID = (
        "SELECT row_id FROM github_project_record WHERE table_name = :table_name AND remote_record_id = :remote_id"
    )
    RESTORE_PROJECT_ROW = "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT(id) DO UPDATE SET {}"
    SET_REFRESH_WATERMARKS = (
        "UPDATE github_repository SET issue_watermark = :issue_watermark, ledger_watermark = :ledger_watermark "
        "WHERE singleton = 1"
    )
    MARK_UNVERIFIABLE = (
        "INSERT INTO github_unverifiable_item(item_id, reason) VALUES (:item_id, :reason) "
        "ON CONFLICT(item_id) DO UPDATE SET reason = excluded.reason"
    )
    CLEAR_UNVERIFIABLE = "DELETE FROM github_unverifiable_item WHERE item_id = :item_id"
    IS_UNVERIFIABLE = "SELECT 1 FROM github_unverifiable_item WHERE item_id = :item_id"
    OWED_REFLECTIONS = "SELECT item_id FROM github_owed_reflection"
    CLEAR_OWED_REFLECTION = "DELETE FROM github_owed_reflection WHERE item_id = :item_id"
    MARK_OWED_REFLECTION = "INSERT OR IGNORE INTO github_owed_reflection(item_id) VALUES (:item_id)"
    UPSERT_ROW = "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}"


class WorkingCopyTable(StrEnum):
    """Closed set of working-copy tables used by snapshot restore."""

    TODO = "todo"
    TODO_STATE = "todo_state"
    TODO_ARTIFACTS = "todo_artifacts"
    TODO_ARTIFACT_VERSIONS = "todo_artifact_versions"
    TODO_DEPS = "todo_deps"
    COMMIT_REVIEW = "commit_review"
    DOCUMENTATION_TRANSFER = "documentation_transfer"
    GITHUB_ARTIFACT_CONTENT = "github_artifact_content"
    GITHUB_PROJECT_RECORD = "github_project_record"
    GITHUB_ITEM = "github_item"
    GITHUB_OWED_REFLECTION = "github_owed_reflection"
    GITHUB_UNVERIFIABLE_ITEM = "github_unverifiable_item"
    GITHUB_REPOSITORY = "github_repository"
    WORKING_COPY_PENDING_ITEM = "working_copy_pending_item"
    WORKING_COPY_PENDING_PROJECT = "working_copy_pending_project"
    WORKING_COPY_CAPTURE_CONTROL = "working_copy_capture_control"


_UNKNOWN_PROJECT_RECORD = "Unknown working-copy project record"
_COMMA_SPACE = ", "
_BIND_PARAMETER = ":{}"
_EXCLUDED_ASSIGNMENT = "{} = excluded.{}"
_TODO_ARTIFACT_CONFLICT_TARGET = "id, name"
_ITEM_RESTORE_TABLES = (
    WorkingCopyTable.TODO_STATE,
    WorkingCopyTable.TODO_ARTIFACTS,
    WorkingCopyTable.TODO_ARTIFACT_VERSIONS,
)
_ITEM_PURGE_TABLES = (*_ITEM_RESTORE_TABLES, WorkingCopyTable.TODO)


_PROJECT_TABLES = (WorkingCopyTable.COMMIT_REVIEW, WorkingCopyTable.DOCUMENTATION_TRANSFER)
_UPSERT_TABLE_COLUMNS: dict[WorkingCopyTable, tuple[str, ...]] = {
    WorkingCopyTable.TODO: (
        "id",
        "slug",
        "ready_since",
        "schedule",
        "group_id",
        "description",
        "status",
        "delivered_at",
        "delivered_commit",
        "children",
        "lineage",
        "entry_point",
        "human_involved",
        "context",
        "removed_at",
        "prev_status",
        "removed_deps",
        "removed_claim",
        "removed_doc_reconciliation",
        "pending_purge_paths",
        "created_at",
        "updated_at",
    ),
    WorkingCopyTable.TODO_STATE: ("id", "slug", "state", "created_at", "updated_at"),
    WorkingCopyTable.TODO_ARTIFACTS: ("id", "slug", "name", "content", "digest", "updated_by", "updated_at"),
    WorkingCopyTable.TODO_ARTIFACT_VERSIONS: (
        "version_id",
        "id",
        "slug",
        "name",
        "content",
        "digest",
        "updated_by",
        "created_at",
    ),
}
_PROJECT_UPSERT_COLUMNS: dict[WorkingCopyTable, tuple[str, ...]] = {
    WorkingCopyTable.COMMIT_REVIEW: (
        "id",
        "sha",
        "verdict",
        "reviewer_session_id",
        "producer_session_ids",
        "stamped_at",
        "reason",
        "migration_source",
    ),
    WorkingCopyTable.DOCUMENTATION_TRANSFER: (
        "id",
        "source_slug",
        "target_slug",
        "parent_id",
        "source_sha",
        "source_path_blobs",
        "target_path_blobs",
        "transition_id",
        "reconciliation_commit",
    ),
}


@dataclass(frozen=True)
class WorkingCopyChanges:
    """Rows changed in one local transaction, split by item and project ownership."""

    item_ids: tuple[str, ...]
    project_records: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class WorkingCopyMoveSet:
    """Open item identities in holder-first order and members detached from finished parents."""

    item_ids: tuple[str, ...]
    detached_item_ids: frozenset[str]


@dataclass(frozen=True)
class WorkingCopyItemSnapshot:
    """Complete persisted state for one work item, independent of SQLAlchemy models."""

    item_id: str
    todo: Mapping[str, object]
    state: Mapping[str, object] | None
    dependencies: tuple[Mapping[str, object], ...]
    artifacts: tuple[Mapping[str, object], ...]
    versions: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class WorkingCopyIssueRelations:
    """Resolved GitHub identities for one item's parent and open dependencies."""

    parent_issue_number: int | None
    parent_issue_id: int | None
    blocked_by_issue_ids: tuple[int, ...]


def pending_changes(session: Session) -> WorkingCopyChanges:
    """Read trigger-captured item and project rows inside the current transaction."""
    item_ids = tuple(str(row[0]) for row in session.execute(text(WorkingCopySql.PENDING_ITEMS)).all())
    project_records = tuple(
        (str(row[0]), int(row[1])) for row in session.execute(text(WorkingCopySql.PENDING_PROJECTS)).all()
    )
    return WorkingCopyChanges(item_ids, project_records)


def item_snapshot(session: Session, item_id: str, *, unpushed_only: bool = False) -> WorkingCopyItemSnapshot | None:
    """Read one item's rows and artifact history through the active transaction."""
    todo = _one(session, WorkingCopySql.TODO_BY_ID, {WorkingCopyField.ITEM_ID: item_id})
    if todo is None:
        return None
    state = _one(session, WorkingCopySql.STATE_BY_ID, {WorkingCopyField.ITEM_ID: item_id})
    dependencies = _all(
        session,
        WorkingCopySql.DEPENDENCIES_BY_ITEM,
        {WorkingCopyField.ITEM_ID: item_id},
    )
    artifacts = _all(session, WorkingCopySql.ARTIFACTS_BY_ITEM, {WorkingCopyField.ITEM_ID: item_id})
    version_query = WorkingCopySql.VERSIONS_BY_ITEM.value
    if unpushed_only:
        version_query += WorkingCopySql.UNPUSHED_VERSION_FILTER.value
    version_query += WorkingCopySql.VERSION_ORDER.value
    versions = _all(session, version_query, {WorkingCopyField.ITEM_ID: item_id})
    return WorkingCopyItemSnapshot(item_id, todo, state, dependencies, artifacts, versions)


def issue_relations(
    session: Session,
    snapshot: WorkingCopyItemSnapshot,
    newly_opened: Mapping[str, tuple[int, int]],
) -> WorkingCopyIssueRelations:
    """Resolve current group and dependency targets, including issues opened in this transaction."""
    parent_issue_number: int | None = None
    parent_issue_id: int | None = None
    group_id = snapshot.todo.get(WorkingCopyField.GROUP_ID)
    if group_id is not None:
        parent_item_id = str(group_id)
        parent_row = _one(session, WorkingCopySql.TODO_BY_ID, {WorkingCopyField.ITEM_ID: parent_item_id})
        if parent_row is not None and parent_row.get(WorkingCopyField.STATUS) == "holder":
            parent_identity = newly_opened.get(parent_item_id)
            parent_bookkeeping = item_bookkeeping(session, parent_item_id)
            if parent_identity is not None:
                parent_issue_number, parent_issue_id = parent_identity
            elif parent_bookkeeping is not None:
                parent_issue_number = _int_or_none(parent_bookkeeping.get(WorkingCopyField.ISSUE_NUMBER))
                parent_issue_id = _int_or_none(parent_bookkeeping.get(WorkingCopyField.ISSUE_ID))

    blocked_by: set[int] = set()
    for dependency in snapshot.dependencies:
        slug = dependency.get(WorkingCopyField.DEPENDS_ON)
        if not isinstance(slug, str):
            continue
        dependency_row = _one(session, WorkingCopySql.TODO_BY_SLUG, {WorkingCopyField.SLUG: slug})
        if dependency_row is None or dependency_row.get(WorkingCopyField.STATUS) not in {
            "active",
            "icebox",
            "holder",
        }:
            continue
        dependency_item_id = str(dependency_row[WorkingCopyField.ID])
        dependency_identity = newly_opened.get(dependency_item_id)
        dependency_bookkeeping = item_bookkeeping(session, dependency_item_id)
        issue_id = (
            dependency_identity[1]
            if dependency_identity is not None
            else _int_or_none(dependency_bookkeeping.get(WorkingCopyField.ISSUE_ID))
            if dependency_bookkeeping is not None
            else None
        )
        if issue_id is not None:
            blocked_by.add(issue_id)
    return WorkingCopyIssueRelations(parent_issue_number, parent_issue_id, tuple(sorted(blocked_by)))


def issue_relation_dependents(session: Session, item_id: str) -> frozenset[str]:
    """Find existing issue rows whose desired relation depends on this newly issued item."""
    todo = _one(session, WorkingCopySql.TODO_BY_ID, {WorkingCopyField.ITEM_ID: item_id})
    if todo is None:
        return frozenset()
    slug = todo.get(WorkingCopyField.SLUG)
    if not isinstance(slug, str):
        return frozenset()
    dependent_ids = {
        str(row[0])
        for row in session.execute(text(WorkingCopySql.DEPENDENTS_BY_SLUG), {WorkingCopyField.SLUG: slug}).all()
    }
    member_ids = {
        str(row[0])
        for row in session.execute(text(WorkingCopySql.GROUP_MEMBERS_BY_ID), {WorkingCopyField.GROUP_ID: item_id}).all()
    }
    return frozenset(dependent_ids | member_ids)


def move_set(session: Session) -> WorkingCopyMoveSet:
    """Read active work plus its open holder ancestry, ordered parent first."""
    rows = session.execute(text(WorkingCopySql.MOVE_SET)).all()
    item_ids = tuple(dict.fromkeys(str(row[0]) for row in rows))
    included = set(item_ids)
    detached = frozenset(str(row[0]) for row in rows if row[1] is not None and str(row[1]) not in included)
    return WorkingCopyMoveSet(item_ids, detached)


def held_item_ids(session: Session) -> frozenset[str]:
    """Read every durable item identity, regardless of lifecycle status."""
    return frozenset(str(row[0]) for row in session.execute(text(WorkingCopySql.HELD_ITEM_IDS)).all())


def all_project_records(session: Session) -> tuple[tuple[str, Mapping[str, object]], ...]:
    """Read every local commit-review and documentation-transfer record."""
    changes = tuple(
        (str(table), int(row[0]))
        for table in _PROJECT_TABLES
        for row in session.execute(text(WorkingCopySql.PROJECT_IDS.value.format(table))).all()
    )
    return project_records(session, changes)


def project_records(
    session: Session, changes: Sequence[tuple[str, int]]
) -> tuple[tuple[str, Mapping[str, object]], ...]:
    """Read changed project-level review and documentation records."""
    records: list[tuple[str, Mapping[str, object]]] = []
    for table, row_id in changes:
        table_key = WorkingCopyTable(table)
        if table_key not in _PROJECT_TABLES:
            raise ValueError(_UNKNOWN_PROJECT_RECORD)
        row = _one(
            session,
            WorkingCopySql.PROJECT_BY_ID.value.format(table_key),
            {WorkingCopyField.ROW_ID: row_id},
        )
        if row is not None:
            records.append((table_key, row))
    return tuple(records)


@contextmanager
def capture_suppressed(session: Session) -> Iterator[None]:
    """Suppress mirror triggers during a trusted snapshot restore."""
    session.execute(text(WorkingCopySql.SUPPRESS_CAPTURE))
    try:
        yield
    finally:
        session.execute(text(WorkingCopySql.RELEASE_CAPTURE))


def defer_foreign_keys(session: Session) -> None:
    """Check foreign keys at commit for the rest of this transaction; SQLite resets it when the transaction ends.

    A rebuild restores every item in one transaction, in the order GitHub lists them, so a grouped todo can arrive
    before the group it belongs to. A group that never arrives still fails the transaction at commit.
    """
    session.execute(text(WorkingCopySql.DEFER_FOREIGN_KEYS))


def restore_item_snapshot(
    session: Session, snapshot: WorkingCopyItemSnapshot, *, capture_changes: bool = False
) -> None:
    """Restore a full item snapshot while preserving row ids, digests and timestamps."""
    capture = nullcontext() if capture_changes else capture_suppressed(session)
    with capture:
        item_id = snapshot.item_id
        slug = str(snapshot.todo[WorkingCopyField.SLUG])
        for table in _ITEM_RESTORE_TABLES:
            session.execute(
                text(WorkingCopySql.DELETE_ITEM_ROW.value.format(table)),
                {WorkingCopyField.ITEM_ID: item_id},
            )
        session.execute(text(WorkingCopySql.DELETE_DEPENDENCIES), {WorkingCopyField.SLUG: slug})
        _upsert(session, WorkingCopyTable.TODO, snapshot.todo)
        if snapshot.state is not None:
            _upsert(session, WorkingCopyTable.TODO_STATE, snapshot.state)
        for dependency in snapshot.dependencies:
            session.execute(text(WorkingCopySql.INSERT_DEPENDENCY), dict(dependency))
        for artifact in snapshot.artifacts:
            _upsert(session, WorkingCopyTable.TODO_ARTIFACTS, artifact)
        for version in snapshot.versions:
            remote_id = version.get(WorkingCopyField.REMOTE_VERSION_ID)
            if not isinstance(remote_id, str) or not remote_id:
                remote_id = uuid4().hex
            local_version_id = artifact_local_version_id(session, item_id, remote_id)
            local_version = dict(version)
            local_version.pop(WorkingCopyField.REMOTE_VERSION_ID, None)
            local_version[WorkingCopyField.VERSION_ID] = local_version_id
            _upsert(session, WorkingCopyTable.TODO_ARTIFACT_VERSIONS, local_version)
            if local_version_id is None:
                local_version_id = int(session.execute(text(WorkingCopySql.LAST_INSERT_ID)).scalar_one())
            digest = local_version.get(WorkingCopyField.DIGEST)
            if not isinstance(digest, str):
                raise ValueError(_ARTIFACT_DIGEST_REQUIRED)
            if not capture_changes:
                save_artifact_comment_ids(session, item_id, local_version_id, (), remote_id, digest)


def purge_item_snapshot(session: Session, item_id: str, slug: str) -> None:
    """Remove a remotely purged item and its local content without emitting another push."""
    with capture_suppressed(session):
        session.execute(
            text(WorkingCopySql.DELETE_DEPENDENCIES_FOR_ITEM),
            {WorkingCopyField.ITEM_ID: item_id, WorkingCopyField.SLUG: slug},
        )
        for table in _ITEM_PURGE_TABLES:
            session.execute(
                text(WorkingCopySql.DELETE_ITEM_ROW.value.format(table)),
                {WorkingCopyField.ITEM_ID: item_id},
            )
        session.execute(text(WorkingCopySql.CLEAR_ARTIFACT_MAPS), {WorkingCopyField.ITEM_ID: item_id})
        session.execute(text(WorkingCopySql.CLEAR_OWED_REFLECTION), {WorkingCopyField.ITEM_ID: item_id})
        session.execute(text(WorkingCopySql.CLEAR_UNVERIFIABLE), {WorkingCopyField.ITEM_ID: item_id})


def clear_pending_changes(session: Session) -> None:
    """Clear changes only after the remote commit point has succeeded."""
    session.execute(text(WorkingCopySql.CLEAR_PENDING_ITEMS))
    session.execute(text(WorkingCopySql.CLEAR_PENDING_PROJECTS))


def acquire_repository_writer(session: Session) -> None:
    """Reserve SQLite's writer before refresh rechecks queued local revisions."""
    session.execute(text(WorkingCopySql.ACQUIRE_REPOSITORY_WRITER))


def item_bookkeeping(session: Session, item_id: str) -> Mapping[str, object] | None:
    """Read the issue and effective-revision reference for one local row id."""
    return _one(session, WorkingCopySql.ITEM_BOOKKEEPING, {WorkingCopyField.ITEM_ID: item_id})


def items_without_issue_id(session: Session) -> tuple[tuple[str, int], ...]:
    """List working-copy rows that predate the GitHub REST issue identity column."""
    rows = session.execute(text(WorkingCopySql.ITEMS_WITHOUT_ISSUE_ID)).all()
    return tuple((str(row[0]), int(row[1])) for row in rows)


def save_issue_projection_digest(session: Session, item_id: str, projection_digest: str) -> None:
    """Persist the last complete projection only after GitHub accepted its writes."""
    session.execute(
        text(WorkingCopySql.SAVE_PROJECTION_DIGEST),
        {WorkingCopyField.ITEM_ID: item_id, WorkingCopyField.PROJECTION_DIGEST: projection_digest},
    )


def save_item_issue_id(session: Session, item_id: str, issue_id: int) -> None:
    """Persist the provider's REST issue ID used by relation endpoints."""
    session.execute(
        text(WorkingCopySql.SAVE_ISSUE_ID),
        {WorkingCopyField.ITEM_ID: item_id, WorkingCopyField.ISSUE_ID: issue_id},
    )


def save_item_bookkeeping(
    session: Session,
    item_id: str,
    *,
    issue_number: int,
    issue_id: int | None = None,
    node_id: str,
    record_comment_id: int | None,
    revision: int,
    base_revision: int,
    projection_digest: str | None = None,
) -> None:
    """Persist the remote identity and revision after its commit point succeeds."""
    session.execute(
        text(WorkingCopySql.SAVE_ITEM_BOOKKEEPING),
        {
            WorkingCopyField.ITEM_ID: item_id,
            WorkingCopyField.ISSUE_NUMBER: issue_number,
            WorkingCopyField.ISSUE_ID: issue_id,
            WorkingCopyField.NODE_ID: node_id,
            WorkingCopyField.RECORD_COMMENT_ID: str(record_comment_id) if record_comment_id is not None else None,
            WorkingCopyField.REVISION: revision,
            WorkingCopyField.BASE_REVISION: base_revision,
            WorkingCopyField.PROJECTION_DIGEST: projection_digest,
        },
    )


def prune_deleted_artifact_versions(session: Session, item_id: str) -> None:
    """Drop local identity mappings whose version rows were removed by the workflow."""
    session.execute(text(WorkingCopySql.PRUNE_ARTIFACT_MAPS), {WorkingCopyField.ITEM_ID: item_id})


def artifact_remote_version_id(session: Session, item_id: str, version_id: int, digest: str) -> str:
    row = _one(
        session,
        WorkingCopySql.ARTIFACT_MAP_BY_LOCAL_ID,
        {WorkingCopyField.ITEM_ID: item_id, WorkingCopyField.VERSION_ID: version_id},
    )
    remote_id = row.get(WorkingCopyField.REMOTE_VERSION_ID) if row is not None else None
    recorded_digest = row.get(WorkingCopyField.DIGEST) if row is not None else None
    if isinstance(remote_id, str) and remote_id and recorded_digest == digest:
        return remote_id
    remote_id = uuid4().hex
    session.execute(
        text(WorkingCopySql.SAVE_ARTIFACT_MAP),
        {
            WorkingCopyField.ITEM_ID: item_id,
            WorkingCopyField.VERSION_ID: version_id,
            WorkingCopyField.REMOTE_VERSION_ID: remote_id,
            WorkingCopyField.DIGEST: digest,
            WorkingCopyField.COMMENT_IDS: json.dumps([]),
        },
    )
    return remote_id


def artifact_local_version_id(session: Session, item_id: str, remote_id: str) -> int | None:
    row = _one(
        session,
        WorkingCopySql.ARTIFACT_LOCAL_ID,
        {WorkingCopyField.ITEM_ID: item_id, WorkingCopyField.REMOTE_ID: remote_id},
    )
    version_id = row.get(WorkingCopyField.VERSION_ID) if row is not None else None
    return version_id if isinstance(version_id, int) else None


def save_artifact_comment_ids(
    session: Session,
    item_id: str,
    version_id: int,
    comment_ids: Sequence[int],
    remote_version_id: str,
    digest: str,
) -> None:
    """Record every content comment after append succeeds."""
    session.execute(
        text(WorkingCopySql.SAVE_ARTIFACT_MAP),
        {
            WorkingCopyField.ITEM_ID: item_id,
            WorkingCopyField.VERSION_ID: version_id,
            WorkingCopyField.REMOTE_VERSION_ID: remote_version_id,
            WorkingCopyField.DIGEST: digest,
            WorkingCopyField.COMMENT_IDS: json.dumps(list(comment_ids)),
        },
    )


def read_repository_bookkeeping(session: Session) -> Mapping[str, object]:
    """Read the GitHub ledger issue and refresh watermarks."""
    row = _one(session, WorkingCopySql.REPOSITORY_BOOKKEEPING, {})
    return row if row is not None else {}


def repository_initialized(path: str | Path) -> bool:
    """Read whether repository reconstruction completed successfully."""
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(WorkingCopySql.REPOSITORY_INITIALIZED).fetchone()
        return row is not None and row[0] == 1
    finally:
        connection.close()


def mark_repository_initialized(session: Session) -> None:
    """Mark the working copy serveable after a complete reconstruction transaction."""
    session.execute(text(WorkingCopySql.MARK_REPOSITORY_INITIALIZED))


def mark_all_issue_reflections_owed(session: Session) -> None:
    """Queue projection repair for every item that already has a repository issue."""
    session.execute(text(WorkingCopySql.MARK_ALL_ISSUE_REFLECTIONS_OWED))


def save_projection_repair_progress(session: Session, issue_number: int) -> None:
    """Record the last fully backfilled issue for an interrupted projection upgrade."""
    session.execute(
        text(WorkingCopySql.SAVE_PROJECTION_REPAIR_PROGRESS),
        {WorkingCopyField.NUMBER: issue_number},
    )


def complete_projection_repair(session: Session, projection_version: int) -> None:
    """Publish a projection version only after all issues and reflections are repaired."""
    session.execute(
        text(WorkingCopySql.COMPLETE_PROJECTION_REPAIR),
        {WorkingCopyField.PROJECTION_VERSION: projection_version},
    )


def save_ledger_issue(session: Session, issue_number: int, node_id: str) -> None:
    """Remember the platform-opened project ledger issue."""
    session.execute(
        text(WorkingCopySql.SAVE_LEDGER_ISSUE),
        {WorkingCopyField.NUMBER: issue_number, WorkingCopyField.NODE_ID: node_id},
    )


def project_remote_record_id(session: Session, table: str, row_id: int) -> str:
    row = _one(
        session,
        WorkingCopySql.PROJECT_MAP_BY_LOCAL_ID,
        {WorkingCopyField.TABLE_NAME: table, WorkingCopyField.ROW_ID: row_id},
    )
    remote_id = row.get(WorkingCopyField.REMOTE_RECORD_ID) if row is not None else None
    if isinstance(remote_id, str) and remote_id:
        return remote_id
    remote_id = uuid4().hex
    session.execute(
        text(WorkingCopySql.SAVE_PROJECT_MAP),
        {
            WorkingCopyField.TABLE_NAME: table,
            WorkingCopyField.ROW_ID: row_id,
            WorkingCopyField.REMOTE_ID: remote_id,
            WorkingCopyField.COMMENT_ID: _EMPTY,
        },
    )
    return remote_id


def mark_project_record_pushed(
    session: Session, table: str, row_id: int, comment_id: int, remote_record_id: str | None = None
) -> None:
    """Mark one project row as represented by a committed ledger comment."""
    table_key = WorkingCopyTable(table)
    if table_key not in _PROJECT_TABLES:
        raise ValueError(_UNKNOWN_PROJECT_RECORD)
    session.execute(
        text(WorkingCopySql.MARK_PROJECT_MAP),
        {
            WorkingCopyField.TABLE_NAME: table_key,
            WorkingCopyField.ROW_ID: row_id,
            WorkingCopyField.REMOTE_RECORD_ID: remote_record_id,
            WorkingCopyField.COMMENT_ID: str(comment_id),
        },
    )


def restore_project_record(
    session: Session,
    table: str,
    row: Mapping[str, object],
    remote_id: str,
    *,
    capture_changes: bool = False,
) -> int:
    """Restore a project-level record carried by a trusted ledger commit."""
    table_key = WorkingCopyTable(table)
    if table_key not in _PROJECT_UPSERT_COLUMNS:
        raise ValueError(_UNKNOWN_PROJECT_RECORD)
    columns = _PROJECT_UPSERT_COLUMNS[table_key]
    names = _COMMA_SPACE.join(columns)
    parameters = _COMMA_SPACE.join(_BIND_PARAMETER.format(column) for column in columns)
    updates = _COMMA_SPACE.join(_EXCLUDED_ASSIGNMENT.format(column, column) for column in columns[1:])
    mapping = _one(
        session,
        WorkingCopySql.PROJECT_MAP_BY_REMOTE_ID,
        {WorkingCopyField.TABLE_NAME: table_key, WorkingCopyField.REMOTE_ID: remote_id},
    )
    mapped_id = mapping.get(WorkingCopyField.ROW_ID) if mapping is not None else None
    local_row_id = mapped_id if isinstance(mapped_id, int) else None
    values = {column: row.get(column) for column in columns}
    values[WorkingCopyField.ID] = local_row_id
    capture = nullcontext() if capture_changes else capture_suppressed(session)
    with capture:
        session.execute(
            text(WorkingCopySql.RESTORE_PROJECT_ROW.value.format(table_key, names, parameters, updates)),
            values,
        )
        if local_row_id is None:
            local_row_id = int(session.execute(text(WorkingCopySql.LAST_INSERT_ID)).scalar_one())
        session.execute(
            text(WorkingCopySql.SAVE_PROJECT_MAP),
            {
                WorkingCopyField.TABLE_NAME: table_key,
                WorkingCopyField.ROW_ID: local_row_id,
                WorkingCopyField.REMOTE_ID: remote_id,
                WorkingCopyField.COMMENT_ID: _EMPTY,
            },
        )
    return local_row_id


def set_refresh_watermarks(session: Session, issue_timestamp: str | None, ledger_comment_id: int | None) -> None:
    """Advance both scan watermarks only after a complete refresh transaction."""
    session.execute(
        text(WorkingCopySql.SET_REFRESH_WATERMARKS),
        {
            WorkingCopyField.ISSUE_WATERMARK: issue_timestamp,
            WorkingCopyField.LEDGER_WATERMARK: str(ledger_comment_id) if ledger_comment_id is not None else None,
        },
    )


def mark_item_unverifiable(session: Session, item_id: str, reason: str) -> None:
    """Record an item whose remote record could not be authenticated or parsed."""
    session.execute(
        text(WorkingCopySql.MARK_UNVERIFIABLE),
        {WorkingCopyField.ITEM_ID: item_id, WorkingCopyField.REASON: reason},
    )


def clear_item_unverifiable(session: Session, item_id: str) -> None:
    """Clear an unverifiable marker after a trustworthy later revision is adopted."""
    session.execute(text(WorkingCopySql.CLEAR_UNVERIFIABLE), {WorkingCopyField.ITEM_ID: item_id})


def item_unverifiable(session: Session, item_id: str) -> bool:
    """Tell whether a prior refresh found remote state that could not be authenticated."""
    return (
        session.execute(text(WorkingCopySql.IS_UNVERIFIABLE), {WorkingCopyField.ITEM_ID: item_id}).first() is not None
    )


def owed_reflections(session: Session) -> tuple[str, ...]:
    """Return local items whose GitHub reflection needs repair."""
    return tuple(str(row[0]) for row in session.execute(text(WorkingCopySql.OWED_REFLECTIONS)).all())


def clear_reflection_owed(session: Session, item_id: str) -> None:
    """Clear the owed marker after GitHub accepted every issue reflection field."""
    session.execute(text(WorkingCopySql.CLEAR_OWED_REFLECTION), {WorkingCopyField.ITEM_ID: item_id})


def mark_reflection_owed(session: Session, item_id: str) -> None:
    """Record that the item's issue projection must be repaired after this commit."""
    session.execute(text(WorkingCopySql.MARK_OWED_REFLECTION), {WorkingCopyField.ITEM_ID: item_id})


def _one(session: Session, statement: str, parameters: Mapping[str, object]) -> Mapping[str, object] | None:
    row = session.execute(text(statement), dict(parameters)).mappings().first()
    return dict(row) if row is not None else None


def _all(session: Session, statement: str, parameters: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return tuple(dict(row) for row in session.execute(text(statement), dict(parameters)).mappings().all())


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _upsert(session: Session, table: str, values: Mapping[str, object]) -> None:
    table_key = WorkingCopyTable(table)
    columns = _UPSERT_TABLE_COLUMNS[table_key]
    names = _COMMA_SPACE.join(columns)
    parameters = _COMMA_SPACE.join(_BIND_PARAMETER.format(column) for column in columns)
    updates = _COMMA_SPACE.join(_EXCLUDED_ASSIGNMENT.format(column, column) for column in columns[1:])
    conflict_target = _TODO_ARTIFACT_CONFLICT_TARGET if table_key is WorkingCopyTable.TODO_ARTIFACTS else columns[0]
    session.execute(
        text(WorkingCopySql.UPSERT_ROW.value.format(table_key, names, parameters, conflict_target, updates)),
        {column: values.get(column) for column in columns},
    )
