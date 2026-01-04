"""Unit tests for terminal session registration."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from teleclaude.core.models import SessionAdapterMetadata
from teleclaude.core.terminal_sessions import ensure_terminal_session, terminal_tmux_name


def _init_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "teleclaude.db"
    monkeypatch.setenv("TELECLAUDE_DB_PATH", str(db_path))
    schema_path = Path(__file__).resolve().parents[2] / "teleclaude" / "core" / "schema.sql"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return db_path


def _insert_terminal_session(
    db_path: Path,
    session_id: str,
    tty_path: str,
    closed: int,
) -> None:
    adapter_metadata = SessionAdapterMetadata().to_json()
    ux_state = json.dumps({"native_tty_path": tty_path})
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id, computer_name, title, tmux_session_name,
                origin_adapter, adapter_metadata, closed, created_at,
                last_activity, terminal_size, working_directory, description, ux_state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?, ?, ?)
            """,
            (
                session_id,
                "TestMachine",
                "Terminal session",
                terminal_tmux_name(tty_path),
                "terminal",
                adapter_metadata,
                closed,
                "160x80",
                "~",
                "Terminal-origin session",
                ux_state,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_ensure_terminal_session_reuses_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _init_db(tmp_path, monkeypatch)
    tty_path = "/dev/ttys050"
    session_id = "11111111-1111-1111-1111-111111111111"
    _insert_terminal_session(db_path, session_id, tty_path, closed=0)

    resolved = ensure_terminal_session(tty_path, parent_pid=123, agent="codex", cwd="~")

    assert resolved == session_id


def test_ensure_terminal_session_creates_new_when_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _init_db(tmp_path, monkeypatch)
    tty_path = "/dev/ttys051"
    closed_id = "22222222-2222-2222-2222-222222222222"
    _insert_terminal_session(db_path, closed_id, tty_path, closed=1)

    resolved = ensure_terminal_session(tty_path, parent_pid=456, agent="codex", cwd="~")

    assert resolved != closed_id

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT session_id, closed
            FROM sessions
            WHERE origin_adapter = 'terminal'
              AND json_extract(ux_state, '$.native_tty_path') = ?
            """,
            (tty_path,),
        ).fetchone()
        assert row is not None
        assert row[0] == resolved
        assert row[1] == 0

        archived = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE session_id = ?",
            (closed_id,),
        ).fetchone()
        assert archived is not None
        assert archived[0] == 0
    finally:
        conn.close()
