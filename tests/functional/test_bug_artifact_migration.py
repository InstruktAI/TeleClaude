"""Functional check: the on-open bug->input artifact migration is correct and idempotent.

Pure in-memory sqlite — no daemon, no I/O, no waiting.
"""

from __future__ import annotations

import sqlite3

import pytest

from teleclaude.constants import ARTIFACT_INPUT
from teleclaude.core.todos_db._base import _migrate_bug_artifact_to_input

pytestmark = pytest.mark.functional

_SCHEMA = "CREATE TABLE todo_artifacts (id TEXT, slug TEXT, name TEXT, content TEXT, PRIMARY KEY (id, name))"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(_SCHEMA)
    return conn


def test_bug_artifact_is_renamed_to_input_preserving_content() -> None:
    conn = _conn()
    body = "Symptom: the thing breaks."
    conn.execute("INSERT INTO todo_artifacts VALUES (?, ?, 'bug', ?)", ("id1", "fix-x", body))

    _migrate_bug_artifact_to_input(conn)

    rows = list(conn.execute("SELECT name, content FROM todo_artifacts WHERE slug = ?", ("fix-x",)))
    assert len(rows) == 1
    name, content = rows[0]
    assert name == ARTIFACT_INPUT
    assert content == body


def test_migration_is_idempotent() -> None:
    conn = _conn()
    conn.execute("INSERT INTO todo_artifacts VALUES (?, ?, 'bug', ?)", ("id1", "fix-x", "symptom"))

    _migrate_bug_artifact_to_input(conn)
    _migrate_bug_artifact_to_input(conn)  # second pass finds no bug rows, must not raise

    bug_count = conn.execute("SELECT count(*) FROM todo_artifacts WHERE name = 'bug'").fetchone()[0]
    input_count = conn.execute("SELECT count(*) FROM todo_artifacts WHERE name = ?", (ARTIFACT_INPUT,)).fetchone()[0]
    assert bug_count == 0
    assert input_count == 1


def test_bug_dropped_when_slug_already_carries_input() -> None:
    conn = _conn()
    existing = "Pre-existing input."
    conn.execute("INSERT INTO todo_artifacts VALUES (?, ?, 'input', ?)", ("id1", "fix-x", existing))
    conn.execute("INSERT INTO todo_artifacts VALUES (?, ?, 'bug', ?)", ("id1", "fix-x", "symptom"))

    _migrate_bug_artifact_to_input(conn)

    rows = list(conn.execute("SELECT name, content FROM todo_artifacts WHERE slug = ?", ("fix-x",)))
    assert len(rows) == 1
    name, content = rows[0]
    assert name == ARTIFACT_INPUT
    assert content == existing  # original input preserved; collided bug row dropped
