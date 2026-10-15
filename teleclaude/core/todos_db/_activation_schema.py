"""The activation's storage: the completion mark, the converted-row record and the enforcement of its two predicates.

``local/projects/teleclaude/design/architecture/workflow-store`` (Activation). The converted-row record is history: one
record per converted row, inserted in the conversion's own transaction and never updated. The store refuses, for a
converted row, an update whose new state lacks the structured workflow record or whose phase is not a phase of the
machine, whichever writer or code version attempts it. The enforcement is a pair of triggers on the state table, so no
writer needs to know of it.
"""

from __future__ import annotations

import sqlite3
from typing import Final

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

MARK_TABLE: Final = "workflow_activation"
CONVERTED_TABLE: Final = "workflow_converted_row"
STATE_GUARD_TRIGGER: Final = "workflow_converted_row_state_guard"
HISTORY_GUARD_TRIGGER: Final = "workflow_converted_row_history_guard"

STATE_GUARD_REFUSAL: Final = (
    "converted row: the new state lacks the structured workflow record or its phase is not a phase of the machine; "
    "read the item again and write from the current state"
)
HISTORY_GUARD_REFUSAL: Final = "the converted-row record is history and is never updated"

_PHASE: Final = "json_extract(NEW.state, '$.lifecycle_phase')"
_KIND: Final = "json_extract(NEW.state, '$.kind')"
_MACHINE_PHASES: Final = "('preparation', 'waiting', 'work', 'ready', 'delivered')"
_TASK_PHASES: Final = "('task_plan_drafting', 'task_running', 'prepared', 'delivered')"
_STATE_ACCEPTABLE: Final = (
    "json_valid(NEW.state) AND json_type(NEW.state, '$.workflow') = 'object' AND ("
    f"({_KIND} = 'task' AND {_PHASE} IN {_TASK_PHASES}) OR "
    f"(({_KIND} IS NULL OR {_KIND} != 'task') AND ({_PHASE} IN {_MACHINE_PHASES} OR "
    f"({_PHASE} = 'prepared' AND json_type(NEW.state, '$.workflow.prepared') = 'object'))))"
)

_CREATE_MARK: Final = (
    f"CREATE TABLE IF NOT EXISTS {MARK_TABLE} (id INTEGER PRIMARY KEY CHECK (id = 1), activated_at TEXT NOT NULL)"
)
_CREATE_CONVERTED: Final = (
    f"CREATE TABLE IF NOT EXISTS {CONVERTED_TABLE} ("
    "row_id TEXT PRIMARY KEY REFERENCES todo(id) ON DELETE CASCADE, "
    "replaced_phase TEXT NOT NULL, converted_at TEXT NOT NULL, "
    "path TEXT NOT NULL CHECK (path IN ('activation', 'restore', 'capability')))"
)
_STATE_GUARD_SQL: Final = (
    f"CREATE TRIGGER {STATE_GUARD_TRIGGER} BEFORE UPDATE OF state ON todo_state FOR EACH ROW "
    f"WHEN EXISTS (SELECT 1 FROM {CONVERTED_TABLE} WHERE row_id = NEW.id) AND NOT COALESCE(({_STATE_ACCEPTABLE}), 0) "
    f"BEGIN SELECT RAISE(ABORT, '{STATE_GUARD_REFUSAL}'); END"
)
_HISTORY_GUARD_SQL: Final = (
    f"CREATE TRIGGER {HISTORY_GUARD_TRIGGER} BEFORE UPDATE ON {CONVERTED_TABLE} FOR EACH ROW "
    f"BEGIN SELECT RAISE(ABORT, '{HISTORY_GUARD_REFUSAL}'); END"
)
_GUARDS: Final = ((STATE_GUARD_TRIGGER, _STATE_GUARD_SQL), (HISTORY_GUARD_TRIGGER, _HISTORY_GUARD_SQL))


def _trigger_sql(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?", (name,)
    ).fetchone()  # guard: raw-sql
    return str(row[0]) if row else ""


def _table_present(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()  # guard: raw-sql
    return row is not None


def ensure_activation_schema(conn: sqlite3.Connection) -> None:
    """Create the mark, the converted-row record and the enforcing triggers; a trigger of another text is replaced.

    Idempotent and additive: it writes no row. It runs after the state table exists, since a trigger names it.
    """
    if not _table_present(conn, "todo_state"):
        return
    conn.execute(_CREATE_MARK)  # guard: raw-sql
    conn.execute(_CREATE_CONVERTED)  # guard: raw-sql
    for name, sql in _GUARDS:
        if _trigger_sql(conn, name) == sql:
            continue
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")  # guard: raw-sql
        conn.execute(sql)  # guard: raw-sql
    conn.commit()


def activation_schema_in_place(conn: sqlite3.Connection) -> bool:
    """Whether the record table and the enforcement of both predicates are in place with the expected text."""
    if not (_table_present(conn, MARK_TABLE) and _table_present(conn, CONVERTED_TABLE)):
        return False
    return all(_trigger_sql(conn, name) == sql for name, sql in _GUARDS)
