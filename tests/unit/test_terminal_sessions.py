"""Unit tests for terminal session registration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from teleclaude.config import config
from teleclaude.core.models import SessionAdapterMetadata
from teleclaude.core.session_utils import build_session_title, get_short_project_name
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
) -> None:
    adapter_metadata = SessionAdapterMetadata().to_json()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id, computer_name, title, tmux_session_name,
                origin_adapter, adapter_metadata, created_at,
                last_activity, terminal_size, working_directory, description, native_tty_path
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?, ?, ?)
            """,
            (
                session_id,
                "TestMachine",
                "Terminal session",
                terminal_tmux_name(tty_path),
                "terminal",
                adapter_metadata,
                "160x80",
                "~",
                "Terminal-origin session",
                tty_path,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_ensure_terminal_session_reuses_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _init_db(tmp_path, monkeypatch)
    tty_path = "/dev/ttys050"
    session_id = "11111111-1111-1111-1111-111111111111"
    _insert_terminal_session(db_path, session_id, tty_path)

    resolved = ensure_terminal_session(tty_path, parent_pid=123, agent="codex", cwd="~")

    assert resolved == session_id


def test_ensure_terminal_session_creates_new_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _init_db(tmp_path, monkeypatch)
    tty_path = "/dev/ttys051"
    resolved = ensure_terminal_session(tty_path, parent_pid=456, agent="codex", cwd="~")

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT session_id
            FROM sessions
            WHERE origin_adapter = 'terminal'
              AND native_tty_path = ?
            """,
            (tty_path,),
        ).fetchone()
        assert row is not None
        assert row[0] == resolved
    finally:
        conn.close()


def test_ensure_terminal_session_sets_title_from_args(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _init_db(tmp_path, monkeypatch)
    tty_path = "/dev/ttys052"
    cwd = config.computer.default_working_dir or "~"
    description = "Untitled"

    resolved = ensure_terminal_session(
        tty_path,
        parent_pid=789,
        agent="codex",
        cwd=cwd,
        thinking_mode="slow",
        description=description,
    )

    expected_title = build_session_title(
        computer_name=config.computer.name,
        short_project=get_short_project_name(cwd, base_project=config.computer.default_working_dir),
        description=description,
        agent_name="codex",
        thinking_mode="slow",
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT title FROM sessions WHERE session_id = ?",
            (resolved,),
        ).fetchone()
        assert row is not None
        assert row[0] == expected_title
    finally:
        conn.close()
