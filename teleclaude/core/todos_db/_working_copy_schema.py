"""Working-copy schema installation for the GitHub adapter's local substrate."""

from __future__ import annotations

import sqlite3
from enum import StrEnum
from pathlib import Path

from teleclaude.core.migration_signal import MigrationStore, signal_migration_started
from teleclaude.core.todos_db._github_board import initialize_board_bookkeeping
from teleclaude.core.todos_db._github_pull_requests import initialize_pull_request_bookkeeping
from teleclaude.core.todos_db._github_questions import initialize_question_bookkeeping
from teleclaude.core.todos_db._ledger_knowledge import LEDGER_COMMIT_DDL, LEDGER_COMMIT_TABLE, LedgerKnowledgeField
from teleclaude.core.todos_db._working_copy import _PROJECT_TABLES, WorkingCopyField, WorkingCopyTable

_BOOKKEEPING_DDL = (
    "CREATE TABLE IF NOT EXISTS github_item (item_id TEXT PRIMARY KEY, issue_number INTEGER, node_id TEXT, "
    "issue_id INTEGER, record_comment_id TEXT, revision INTEGER NOT NULL DEFAULT 0, base_revision INTEGER NOT NULL DEFAULT 0, "
    "projection_digest TEXT)",
    "CREATE TABLE IF NOT EXISTS github_artifact_content (item_id TEXT NOT NULL, version_id INTEGER NOT NULL, "
    "remote_version_id TEXT, digest TEXT, comment_ids TEXT NOT NULL, PRIMARY KEY(item_id, version_id), "
    "UNIQUE(item_id, remote_version_id))",
    "CREATE TABLE IF NOT EXISTS github_project_record (table_name TEXT NOT NULL, row_id INTEGER NOT NULL, "
    "remote_record_id TEXT, comment_id TEXT, PRIMARY KEY(table_name, row_id), "
    "UNIQUE(table_name, remote_record_id))",
    "CREATE TABLE IF NOT EXISTS github_owed_reflection (item_id TEXT PRIMARY KEY)",
    "CREATE TABLE IF NOT EXISTS github_unverifiable_item (item_id TEXT PRIMARY KEY, reason TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS github_refresh_watermark (name TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS github_repository (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), "
    "ledger_issue_number INTEGER, ledger_node_id TEXT, issue_watermark TEXT, ledger_watermark TEXT, "
    "initialized INTEGER NOT NULL DEFAULT 0, projection_version INTEGER NOT NULL DEFAULT 0, "
    "projection_repair_after_issue INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS working_copy_pending_item (item_id TEXT PRIMARY KEY)",
    "CREATE TABLE IF NOT EXISTS working_copy_pending_project (table_name TEXT NOT NULL, row_id INTEGER NOT NULL, "
    "PRIMARY KEY(table_name, row_id))",
    "CREATE TABLE IF NOT EXISTS working_copy_capture_control (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), "
    "suppressed INTEGER NOT NULL DEFAULT 0)",
)
# Each singleton row is created once and never deleted, so a presence read decides the seed without the
# writer: INSERT OR IGNORE needs writer admission even when it ignores the row.
_SINGLETON_SEEDS = (
    (
        "SELECT 1 FROM github_repository WHERE singleton = 1",
        "INSERT OR IGNORE INTO github_repository(singleton) VALUES (1)",
    ),
    (
        "SELECT 1 FROM working_copy_capture_control WHERE singleton = 1",
        "INSERT OR IGNORE INTO working_copy_capture_control(singleton, suppressed) VALUES (1, 0)",
    ),
)
_REPOSITORY_COLUMNS_SQL = "PRAGMA table_info(github_repository)"
_TABLE_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
_TABLE_INFO_SQL = "PRAGMA table_info({})"
_ADD_COLUMN_SQL = "ALTER TABLE {} ADD COLUMN {} {}"
_INITIALIZED_COLUMN_DDL = "ALTER TABLE github_repository ADD COLUMN initialized INTEGER NOT NULL DEFAULT 0"
_ITEM_TRIGGER_SQL = (
    "CREATE TRIGGER IF NOT EXISTS {trigger} AFTER {operation} ON {table} "
    "WHEN (SELECT suppressed FROM working_copy_capture_control WHERE singleton = 1) = 0 "
    "BEGIN INSERT OR IGNORE INTO working_copy_pending_item(item_id) "
    "SELECT {expression} WHERE {expression} IS NOT NULL; END"
)
_PROJECT_TRIGGER_SQL = (
    "CREATE TRIGGER IF NOT EXISTS {trigger} AFTER {operation} ON {table} "
    "WHEN (SELECT suppressed FROM working_copy_capture_control WHERE singleton = 1) = 0 "
    "BEGIN INSERT OR IGNORE INTO working_copy_pending_project(table_name, row_id) "
    "VALUES ('{table}', {row}.id); END"
)
_NEW_PREFIX = "NEW."
_ROW_DOT = "."
_TRIGGER_PREFIX = "github_capture_{}"
_UNDERSCORE = "_"


class TriggerOperation(StrEnum):
    """Closed set of SQLite trigger operations installed for local changes."""

    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class TriggerRow(StrEnum):
    """Closed set of SQLite trigger row aliases used in trigger expressions."""

    OLD = "OLD"
    NEW = "NEW"


_WORKING_COPY_COLUMN_MIGRATIONS = (
    (WorkingCopyTable.GITHUB_ARTIFACT_CONTENT, WorkingCopyField.REMOTE_VERSION_ID, "TEXT"),
    (WorkingCopyTable.GITHUB_ARTIFACT_CONTENT, WorkingCopyField.DIGEST, "TEXT"),
    (WorkingCopyTable.GITHUB_PROJECT_RECORD, WorkingCopyField.REMOTE_RECORD_ID, "TEXT"),
    (WorkingCopyTable.GITHUB_ITEM, WorkingCopyField.ISSUE_ID, "INTEGER"),
    (WorkingCopyTable.GITHUB_ITEM, WorkingCopyField.PROJECTION_DIGEST, "TEXT"),
    (WorkingCopyTable.GITHUB_REPOSITORY, WorkingCopyField.PROJECTION_VERSION, "INTEGER NOT NULL DEFAULT 0"),
    (
        WorkingCopyTable.GITHUB_REPOSITORY,
        WorkingCopyField.PROJECTION_REPAIR_AFTER_ISSUE,
        "INTEGER NOT NULL DEFAULT 0",
    ),
    (WorkingCopyTable.GITHUB_REPOSITORY, LedgerKnowledgeField.THROUGH, "TEXT"),
)


_ITEM_TRIGGERS: tuple[tuple[WorkingCopyTable, str], ...] = (
    (WorkingCopyTable.TODO, "NEW.id"),
    (WorkingCopyTable.TODO_STATE, "NEW.id"),
    (WorkingCopyTable.TODO_ARTIFACTS, "NEW.id"),
    (WorkingCopyTable.TODO_ARTIFACT_VERSIONS, "NEW.id"),
    (WorkingCopyTable.TODO_DEPS, "(SELECT id FROM todo WHERE slug = NEW.slug LIMIT 1)"),
)


def initialize_working_copy(path: str | Path) -> None:
    """Install working-copy bookkeeping and change capture after every schema bootstrap."""
    connection = sqlite3.connect(path)
    try:
        if connection.execute(_TABLE_EXISTS_SQL, (LEDGER_COMMIT_TABLE,)).fetchone() is None:
            if (
                connection.execute(_TABLE_EXISTS_SQL, (WorkingCopyTable.GITHUB_REPOSITORY.value,)).fetchone()
                is not None
            ):
                signal_migration_started(MigrationStore.TODOS)
            connection.execute(LEDGER_COMMIT_DDL)
        for statement in _BOOKKEEPING_DDL:
            connection.execute(statement)
        for presence_sql, seed_sql in _SINGLETON_SEEDS:
            if connection.execute(presence_sql).fetchone() is None:
                connection.execute(seed_sql)
        initialize_question_bookkeeping(connection)
        initialize_pull_request_bookkeeping(connection)
        initialize_board_bookkeeping(connection)
        repository_columns = {str(row[1]) for row in connection.execute(_REPOSITORY_COLUMNS_SQL)}
        if WorkingCopyField.INITIALIZED not in repository_columns:
            signal_migration_started(MigrationStore.TODOS)
            connection.execute(_INITIALIZED_COLUMN_DDL)
        for table_name, column, column_type in _WORKING_COPY_COLUMN_MIGRATIONS:
            columns = {str(row[1]) for row in connection.execute(_TABLE_INFO_SQL.format(table_name))}
            if column not in columns:
                signal_migration_started(MigrationStore.TODOS)
                connection.execute(_ADD_COLUMN_SQL.format(table_name, column, column_type))
        for table, item_id in _ITEM_TRIGGERS:
            for operation in TriggerOperation:
                row = TriggerRow.OLD if operation is TriggerOperation.DELETE else TriggerRow.NEW
                expression = item_id.replace(_NEW_PREFIX, str(row) + _ROW_DOT)
                trigger = _TRIGGER_PREFIX.format(table) + _UNDERSCORE + operation.lower()
                connection.execute(
                    _ITEM_TRIGGER_SQL.format(trigger=trigger, operation=operation, table=table, expression=expression)
                )
        for table in _PROJECT_TABLES:
            for operation in TriggerOperation:
                row = TriggerRow.OLD if operation is TriggerOperation.DELETE else TriggerRow.NEW
                trigger = _TRIGGER_PREFIX.format(table) + _UNDERSCORE + operation.lower()
                connection.execute(
                    _PROJECT_TRIGGER_SQL.format(trigger=trigger, operation=operation, table=table, row=row)
                )
        connection.commit()
    finally:
        connection.close()
