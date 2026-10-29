"""Working-copy bookkeeping for artifacts kept as native GitHub issue artifacts.

An item's committed record names each artifact by its issue-artifact number and lists the versions GitHub still
serves. The copy mirrors that: where each artifact lives, which of its versions a committed record names, and the
republication state of items whose record still predates native artifacts.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import text
from sqlalchemy.orm import Session

from teleclaude.core.todos_db._working_copy import capture_suppressed

__all__ = [
    "REPUBLICATION_FINALIZING_KEY",
    "REQUESTED_ITEMS_KEY",
    "ArtifactFact",
    "CommittedArtifact",
    "CommittedEntry",
    "EntryRow",
    "ProgressRow",
    "RepublicationWait",
    "any_republication_pending",
    "artifact_address",
    "clear_artifact_deletion",
    "clear_republication_item",
    "committed_entries",
    "initialize_artifact_bookkeeping",
    "issue_artifacts_fact",
    "keep_hydrated_version",
    "mark_pending_item",
    "mark_republication_requested",
    "owed_artifact_deletions",
    "queue_artifact_deletion",
    "read_republication_wait",
    "republication_order",
    "republication_pending",
    "republication_progress",
    "save_committed_artifacts",
    "save_issue_artifacts_fact",
    "save_republication_progress",
    "save_republication_wait",
    "unlink_missing_versions",
    "version_entry",
]

REPUBLICATION_FINALIZING_KEY = "github_republication_finalizing"
REQUESTED_ITEMS_KEY = "github_republication_requested"
_ACTIVE_RUNNER = "active_runner"

_ADDRESS_DDL = (
    "CREATE TABLE IF NOT EXISTS github_artifact_address (item_id TEXT NOT NULL, name TEXT NOT NULL, "
    "artifact_number INTEGER NOT NULL, PRIMARY KEY(item_id, name))"
)
_ENTRY_DDL = (
    "CREATE TABLE IF NOT EXISTS github_artifact_entry (item_id TEXT NOT NULL, name TEXT NOT NULL, "
    "ordinal INTEGER NOT NULL, digest TEXT NOT NULL, updated_by TEXT, created_at TEXT, version_id INTEGER, "
    "PRIMARY KEY(item_id, name, ordinal))"
)
_PENDING_DDL = (
    "CREATE TABLE IF NOT EXISTS github_republication_pending (item_id TEXT PRIMARY KEY, "
    "requested INTEGER NOT NULL DEFAULT 0)"
)
_PROGRESS_DDL = (
    "CREATE TABLE IF NOT EXISTS github_republication_progress (item_id TEXT NOT NULL, name TEXT NOT NULL, "
    "version_id INTEGER NOT NULL, digest TEXT NOT NULL, artifact_number INTEGER NOT NULL, "
    "PRIMARY KEY(item_id, name, version_id))"
)
_DELETION_DDL = (
    "CREATE TABLE IF NOT EXISTS github_artifact_deletion (issue_number INTEGER NOT NULL, "
    "artifact_number INTEGER NOT NULL, PRIMARY KEY(issue_number, artifact_number))"
)
_PENDING_PRESENT_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'github_republication_pending'"
# Every item the copy already holds on GitHub carries a record that predates native artifacts.
_SEED_PENDING_SQL = (
    "INSERT OR IGNORE INTO github_republication_pending(item_id) SELECT i.item_id FROM github_item AS i "
    "WHERE i.issue_number IS NOT NULL AND i.item_id IN (SELECT CAST(id AS TEXT) FROM todo)"
)
_RETIRED_CONTENT_TABLE_SQL = "DROP TABLE IF EXISTS github_artifact_content"


class ArtifactFact(StrEnum):
    """What the working copy has learned about whether the repository serves issue artifacts."""

    SERVED = "served"
    NOT_SERVED = "not_served"


class _Field(StrEnum):
    ITEM_ID = "item_id"
    NAME = "name"
    ORDINAL = "ordinal"
    DIGEST = "digest"
    UPDATED_BY = "updated_by"
    CREATED_AT = "created_at"
    VERSION_ID = "version_id"
    ARTIFACT_NUMBER = "artifact_number"
    ISSUE_NUMBER = "issue_number"
    REQUESTED = "requested"
    FACT = "fact"
    NOT_BEFORE = "not_before"
    BACKOFF = "backoff"
    CONTENT = "content"


class _Sql(StrEnum):
    DELETE_ADDRESSES = "DELETE FROM github_artifact_address WHERE item_id = :item_id"
    DELETE_ENTRIES = "DELETE FROM github_artifact_entry WHERE item_id = :item_id AND name = :name"
    ADDRESS = (
        "INSERT INTO github_artifact_address(item_id, name, artifact_number) VALUES (:item_id, :name, :artifact_number) "
        "ON CONFLICT(item_id, name) DO UPDATE SET artifact_number = excluded.artifact_number"
    )
    KEEP_ENTRIES = (
        "DELETE FROM github_artifact_entry WHERE item_id = :item_id AND name NOT IN "
        "(SELECT name FROM github_artifact_address WHERE item_id = :item_id)"
    )
    ENTRY = (
        "INSERT INTO github_artifact_entry(item_id, name, ordinal, digest, updated_by, created_at, version_id) "
        "VALUES (:item_id, :name, :ordinal, :digest, :updated_by, :created_at, "
        "(SELECT version_id FROM todo_artifact_versions WHERE id = :item_id AND name = :name AND digest = :digest "
        "AND created_at IS :created_at ORDER BY version_id DESC LIMIT 1)) "
        "ON CONFLICT(item_id, name, ordinal) DO UPDATE SET digest = excluded.digest, "
        "updated_by = excluded.updated_by, created_at = excluded.created_at, "
        "version_id = COALESCE(excluded.version_id, "
        "CASE WHEN github_artifact_entry.digest = excluded.digest THEN github_artifact_entry.version_id END)"
    )
    ADDRESS_OF = "SELECT artifact_number FROM github_artifact_address WHERE item_id = :item_id AND name = :name"
    ENTRIES = (
        "SELECT name, ordinal, digest, updated_by, created_at, version_id FROM github_artifact_entry "
        "WHERE item_id = :item_id ORDER BY name, ordinal"
    )
    ENTRY_BY_DIGEST = (
        "SELECT name, ordinal, digest, updated_by, created_at, version_id FROM github_artifact_entry "
        "WHERE item_id = :item_id AND name = :name AND digest = :digest ORDER BY ordinal DESC LIMIT 1"
    )
    UNLINK_MISSING = (
        "UPDATE github_artifact_entry SET version_id = NULL WHERE item_id = :item_id AND version_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM todo_artifact_versions WHERE id = :item_id "
        "AND version_id = github_artifact_entry.version_id)"
    )
    PENDING = "SELECT 1 FROM github_republication_pending WHERE item_id = :item_id"
    ANY_PENDING = "SELECT 1 FROM github_republication_pending LIMIT 1"
    ORDER = (
        "SELECT p.item_id, p.requested, i.issue_number, s.state FROM github_republication_pending AS p "
        "LEFT JOIN github_item AS i ON i.item_id = p.item_id "
        "LEFT JOIN todo_state AS s ON CAST(s.id AS TEXT) = p.item_id"
    )
    REQUESTED = "UPDATE github_republication_pending SET requested = 1 WHERE item_id = :item_id"
    CLEAR_PENDING = "DELETE FROM github_republication_pending WHERE item_id = :item_id"
    CLEAR_PROGRESS = "DELETE FROM github_republication_progress WHERE item_id = :item_id"
    SAVE_PROGRESS = (
        "INSERT INTO github_republication_progress(item_id, name, version_id, digest, artifact_number) "
        "VALUES (:item_id, :name, :version_id, :digest, :artifact_number) "
        "ON CONFLICT(item_id, name, version_id) DO UPDATE SET digest = excluded.digest, "
        "artifact_number = excluded.artifact_number"
    )
    PROGRESS = (
        "SELECT name, version_id, digest, artifact_number FROM github_republication_progress "
        "WHERE item_id = :item_id ORDER BY version_id"
    )
    QUEUE_DELETION = "INSERT OR IGNORE INTO github_artifact_deletion(issue_number, artifact_number) VALUES (:issue_number, :artifact_number)"
    OWED_DELETIONS = (
        "SELECT issue_number, artifact_number FROM github_artifact_deletion ORDER BY issue_number, artifact_number"
    )
    CLEAR_DELETION = (
        "DELETE FROM github_artifact_deletion WHERE issue_number = :issue_number AND artifact_number = :artifact_number"
    )
    FACT = "SELECT issue_artifacts FROM github_repository WHERE singleton = 1"
    SAVE_FACT = "UPDATE github_repository SET issue_artifacts = :fact WHERE singleton = 1"
    WAIT = "SELECT republication_not_before, republication_backoff FROM github_repository WHERE singleton = 1"
    SAVE_WAIT = (
        "UPDATE github_repository SET republication_not_before = :not_before, republication_backoff = :backoff "
        "WHERE singleton = 1"
    )
    INSERT_VERSION = (
        "INSERT INTO todo_artifact_versions(id, slug, name, content, digest, updated_by, created_at) "
        "VALUES (:item_id, (SELECT slug FROM todo WHERE CAST(id AS TEXT) = :item_id), :name, :content, :digest, "
        ":updated_by, :created_at)"
    )
    LAST_INSERT = "SELECT last_insert_rowid()"
    LINK_ENTRY = (
        "UPDATE github_artifact_entry SET version_id = :version_id "
        "WHERE item_id = :item_id AND name = :name AND ordinal = :ordinal"
    )
    MARK_PENDING_ITEM = "INSERT OR IGNORE INTO working_copy_pending_item(item_id) VALUES (:item_id)"


@dataclass(frozen=True)
class CommittedEntry:
    """One version a committed record names: its position, content digest and non-content working-copy row."""

    ordinal: int
    digest: str
    updated_by: str | None
    created_at: str | None


@dataclass(frozen=True)
class CommittedArtifact:
    """One artifact a committed record names and the versions it lists, oldest first."""

    name: str
    artifact_number: int
    entries: tuple[CommittedEntry, ...]


@dataclass(frozen=True)
class EntryRow:
    """A named version as the copy holds it; `version_id` is None while its content is not local."""

    name: str
    ordinal: int
    digest: str
    updated_by: str | None
    created_at: str | None
    version_id: int | None


@dataclass(frozen=True)
class ProgressRow:
    """A republication save GitHub acknowledged that no committed record names yet."""

    name: str
    version_id: int
    digest: str
    artifact_number: int


def initialize_artifact_bookkeeping(connection: sqlite3.Connection) -> None:
    """Install artifact bookkeeping; a copy that held items before it existed owes each of them republication."""
    seed = connection.execute(_PENDING_PRESENT_SQL).fetchone() is None
    for statement in (_ADDRESS_DDL, _ENTRY_DDL, _PENDING_DDL, _PROGRESS_DDL, _DELETION_DDL, _RETIRED_CONTENT_TABLE_SQL):
        connection.execute(statement)
    if seed:
        connection.execute(_SEED_PENDING_SQL)


def save_committed_artifacts(session: Session, item_id: str, artifacts: Iterable[CommittedArtifact]) -> None:
    """Mirror a committed record: addresses, and every version it names linked to the local row holding its content.

    Entries the record has dropped (GitHub serves only the newest versions) stay while their artifact lives, so a
    version the copy still holds is never taken for unsaved. An artifact the record no longer names loses its rows.
    """
    session.execute(text(_Sql.DELETE_ADDRESSES), {_Field.ITEM_ID: item_id})
    for artifact in artifacts:
        session.execute(
            text(_Sql.ADDRESS),
            {_Field.ITEM_ID: item_id, _Field.NAME: artifact.name, _Field.ARTIFACT_NUMBER: artifact.artifact_number},
        )
        for entry in artifact.entries:
            session.execute(
                text(_Sql.ENTRY),
                {
                    _Field.ITEM_ID: item_id,
                    _Field.NAME: artifact.name,
                    _Field.ORDINAL: entry.ordinal,
                    _Field.DIGEST: entry.digest,
                    _Field.UPDATED_BY: entry.updated_by,
                    _Field.CREATED_AT: entry.created_at,
                },
            )
    session.execute(text(_Sql.KEEP_ENTRIES), {_Field.ITEM_ID: item_id})


def artifact_address(session: Session, item_id: str, name: str) -> int | None:
    """The issue-artifact number a committed record gave the artifact."""
    number = session.execute(text(_Sql.ADDRESS_OF), {_Field.ITEM_ID: item_id, _Field.NAME: name}).scalar_one_or_none()
    return number if isinstance(number, int) else None


def committed_entries(session: Session, item_id: str) -> tuple[EntryRow, ...]:
    """Every version of the item a committed record names, grouped by artifact and oldest first."""
    rows = session.execute(text(_Sql.ENTRIES), {_Field.ITEM_ID: item_id}).mappings().all()
    return tuple(_entry_row(dict(row)) for row in rows)


def version_entry(session: Session, item_id: str, name: str, digest: str) -> EntryRow | None:
    """The newest version of an artifact that a committed record names with this digest."""
    row = (
        session.execute(text(_Sql.ENTRY_BY_DIGEST), {_Field.ITEM_ID: item_id, _Field.NAME: name, _Field.DIGEST: digest})
        .mappings()
        .first()
    )
    return _entry_row(dict(row)) if row is not None else None


def unlink_missing_versions(session: Session, item_id: str) -> None:
    """Forget the local row of a named version the workflow deleted; the record still names the version."""
    session.execute(text(_Sql.UNLINK_MISSING), {_Field.ITEM_ID: item_id})


def republication_pending(session: Session, item_id: str) -> bool:
    """Whether the item's committed record still predates native artifacts."""
    return session.execute(text(_Sql.PENDING), {_Field.ITEM_ID: item_id}).first() is not None


def any_republication_pending(session: Session) -> bool:
    return session.execute(text(_Sql.ANY_PENDING)).first() is not None


def republication_order(session: Session) -> tuple[str, ...]:
    """The pending items in the order republication takes them: requested, then with a live claim, then by issue."""
    rows = session.execute(text(_Sql.ORDER)).all()

    def key(row: Sequence[object]) -> tuple[int, int, int]:
        issue_number = row[2]
        return (0 if row[1] else 1, 0 if _claimed(row[3]) else 1, issue_number if isinstance(issue_number, int) else 0)

    return tuple(str(row[0]) for row in sorted(rows, key=key))


def mark_republication_requested(session: Session, item_id: str) -> None:
    """Record that a write to the item was refused, moving it to the front of republication."""
    session.execute(text(_Sql.REQUESTED), {_Field.ITEM_ID: item_id})


def clear_republication_item(session: Session, item_id: str) -> None:
    """Leave the pending set: the item's schema-2 record is committed, so its save progress is spent."""
    session.execute(text(_Sql.CLEAR_PENDING), {_Field.ITEM_ID: item_id})
    session.execute(text(_Sql.CLEAR_PROGRESS), {_Field.ITEM_ID: item_id})


def save_republication_progress(
    session: Session, item_id: str, name: str, version_id: int, digest: str, artifact_number: int
) -> None:
    """Record one acknowledged republication save, with the artifact's address on creation."""
    session.execute(
        text(_Sql.SAVE_PROGRESS),
        {
            _Field.ITEM_ID: item_id,
            _Field.NAME: name,
            _Field.VERSION_ID: version_id,
            _Field.DIGEST: digest,
            _Field.ARTIFACT_NUMBER: artifact_number,
        },
    )


def republication_progress(session: Session, item_id: str) -> tuple[ProgressRow, ...]:
    """The republication saves GitHub acknowledged for the item, oldest first."""
    rows = session.execute(text(_Sql.PROGRESS), {_Field.ITEM_ID: item_id}).mappings().all()
    return tuple(
        ProgressRow(
            str(row[_Field.NAME]),
            int(row[_Field.VERSION_ID]),
            str(row[_Field.DIGEST]),
            int(row[_Field.ARTIFACT_NUMBER]),
        )
        for row in rows
    )


def queue_artifact_deletion(session: Session, issue_number: int, artifact_number: int) -> None:
    """Owe the deletion of a native artifact whose workflow artifact the committed record marked removed."""
    session.execute(
        text(_Sql.QUEUE_DELETION), {_Field.ISSUE_NUMBER: issue_number, _Field.ARTIFACT_NUMBER: artifact_number}
    )


def owed_artifact_deletions(session: Session) -> tuple[tuple[int, int], ...]:
    """The (issue, artifact) pairs whose deletion is owed."""
    return tuple((int(row[0]), int(row[1])) for row in session.execute(text(_Sql.OWED_DELETIONS)).all())


def clear_artifact_deletion(session: Session, issue_number: int, artifact_number: int) -> None:
    session.execute(
        text(_Sql.CLEAR_DELETION), {_Field.ISSUE_NUMBER: issue_number, _Field.ARTIFACT_NUMBER: artifact_number}
    )


def issue_artifacts_fact(session: Session) -> ArtifactFact | None:
    """What the copy knows of the repository serving issue artifacts; None while unknown."""
    value = session.execute(text(_Sql.FACT)).scalar_one_or_none()
    return ArtifactFact(value) if isinstance(value, str) and value in set(ArtifactFact) else None


def save_issue_artifacts_fact(session: Session, fact: ArtifactFact) -> None:
    session.execute(text(_Sql.SAVE_FACT), {_Field.FACT: fact.value})


@dataclass(frozen=True)
class RepublicationWait:
    """The time before which the daemon's automatic refresh sends nothing, and the pause the next throttle doubles."""

    not_before: datetime | None
    backoff_seconds: int


def save_republication_wait(session: Session, wait: RepublicationWait) -> None:
    session.execute(
        text(_Sql.SAVE_WAIT),
        {
            _Field.NOT_BEFORE: wait.not_before.isoformat() if wait.not_before is not None else None,
            _Field.BACKOFF: wait.backoff_seconds,
        },
    )


def read_republication_wait(session: Session) -> RepublicationWait:
    row = session.execute(text(_Sql.WAIT)).first()
    if row is None:
        return RepublicationWait(None, 0)
    return RepublicationWait(
        datetime.fromisoformat(row[0]) if isinstance(row[0], str) else None, row[1] if isinstance(row[1], int) else 0
    )


def keep_hydrated_version(session: Session, item_id: str, entry: EntryRow, content: str) -> None:
    """Keep a named version read back from GitHub as a local row, without making the item look changed."""
    with capture_suppressed(session):
        session.execute(
            text(_Sql.INSERT_VERSION),
            {
                _Field.ITEM_ID: item_id,
                _Field.NAME: entry.name,
                _Field.CONTENT: content,
                _Field.DIGEST: entry.digest,
                _Field.UPDATED_BY: entry.updated_by,
                _Field.CREATED_AT: entry.created_at,
            },
        )
        version_id = int(session.execute(text(_Sql.LAST_INSERT)).scalar_one())
    session.execute(
        text(_Sql.LINK_ENTRY),
        {
            _Field.VERSION_ID: version_id,
            _Field.ITEM_ID: item_id,
            _Field.NAME: entry.name,
            _Field.ORDINAL: entry.ordinal,
        },
    )


def mark_pending_item(session: Session, item_id: str) -> None:
    """Make the next commit push the item although none of its rows changed."""
    session.execute(text(_Sql.MARK_PENDING_ITEM), {_Field.ITEM_ID: item_id})


def _entry_row(row: Mapping[str, object]) -> EntryRow:
    updated_by = row[_Field.UPDATED_BY]
    created_at = row[_Field.CREATED_AT]
    version_id = row[_Field.VERSION_ID]
    return EntryRow(
        str(row[_Field.NAME]),
        int(str(row[_Field.ORDINAL])),
        str(row[_Field.DIGEST]),
        updated_by if isinstance(updated_by, str) else None,
        created_at if isinstance(created_at, str) else None,
        version_id if isinstance(version_id, int) else None,
    )


def _claimed(state: object) -> bool:
    """Whether the item's state names a live claim; an unreadable state names none."""
    if not isinstance(state, str):
        return False
    try:
        values = json.loads(state)
    except json.JSONDecodeError:
        return False
    return isinstance(values, dict) and bool(values.get(_ACTIVE_RUNNER))
