"""Unit tests for telec session listing helpers."""

import json
import sqlite3

import pytest

from teleclaude.cli import telec


def _create_sessions_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            title TEXT,
            origin_adapter TEXT,
            tmux_session_name TEXT,
            working_directory TEXT,
            last_activity TEXT,
            created_at TEXT,
            ux_state TEXT
        )
        """
    )
    conn.commit()


def test_resolve_session_selection_by_index_and_prefix() -> None:
    entries = [
        telec.SessionListEntry(
            index=1,
            session_id="abc12345",
            title="Alpha",
            origin_adapter="terminal",
            tmux_session_name="telec_abc1",
            working_directory=None,
            last_activity=None,
            created_at=None,
            active_agent=None,
            thinking_mode=None,
            tmux_ready=True,
        ),
        telec.SessionListEntry(
            index=2,
            session_id="def67890",
            title="Beta",
            origin_adapter="terminal",
            tmux_session_name="telec_def6",
            working_directory=None,
            last_activity=None,
            created_at=None,
            active_agent=None,
            thinking_mode=None,
            tmux_ready=True,
        ),
    ]

    assert telec._resolve_session_selection("1", entries) == entries[0]
    assert telec._resolve_session_selection("abc", entries) == entries[0]
    assert telec._resolve_session_selection("telec_abc", entries) == entries[0]


def test_resolve_session_selection_multiple_matches() -> None:
    entries = [
        telec.SessionListEntry(
            index=1,
            session_id="abc111",
            title="Alpha",
            origin_adapter="terminal",
            tmux_session_name="telec_abc1",
            working_directory=None,
            last_activity=None,
            created_at=None,
            active_agent=None,
            thinking_mode=None,
            tmux_ready=True,
        ),
        telec.SessionListEntry(
            index=2,
            session_id="abc222",
            title="Beta",
            origin_adapter="terminal",
            tmux_session_name="telec_abc2",
            working_directory=None,
            last_activity=None,
            created_at=None,
            active_agent=None,
            thinking_mode=None,
            tmux_ready=True,
        ),
    ]

    with pytest.raises(ValueError, match="Multiple sessions match"):
        telec._resolve_session_selection("abc", entries)


def test_load_sessions_parses_ux_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telec, "_tmux_session_exists", lambda _: True)

    conn = sqlite3.connect(":memory:")
    try:
        _create_sessions_table(conn)
        ux_state = json.dumps({"active_agent": "claude", "thinking_mode": "fast"})
        conn.execute(
            """
            INSERT INTO sessions (
                session_id, title, origin_adapter, tmux_session_name,
                working_directory, last_activity, created_at, ux_state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "abc12345",
                "Test Session",
                "terminal",
                "telec_abc1",
                "/tmp",
                "2025-01-01 10:00:00",
                "2025-01-01 09:00:00",
                ux_state,
            ),
        )
        conn.commit()

        entries = telec._load_sessions(conn)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.active_agent == "claude"
        assert entry.thinking_mode == "fast"
        assert entry.tmux_ready is True
        assert entry.working_directory == "/tmp"
    finally:
        conn.close()


def test_resolve_tmux_name_prefers_existing() -> None:
    entry = telec.SessionListEntry(
        index=1,
        session_id="abc12345",
        title="Alpha",
        origin_adapter="telegram",
        tmux_session_name="teleclaude_123",
        working_directory=None,
        last_activity=None,
        created_at=None,
        active_agent=None,
        thinking_mode=None,
        tmux_ready=False,
    )
    assert telec._resolve_tmux_name(entry) == "teleclaude_123"


def test_resolve_tmux_name_terminal_fallback() -> None:
    entry = telec.SessionListEntry(
        index=1,
        session_id="abc12345",
        title="Alpha",
        origin_adapter="terminal",
        tmux_session_name="",
        working_directory=None,
        last_activity=None,
        created_at=None,
        active_agent=None,
        thinking_mode=None,
        tmux_ready=False,
    )
    assert telec._resolve_tmux_name(entry) == "telec_abc12345"


def test_resolve_tmux_name_missing_for_nonterminal() -> None:
    entry = telec.SessionListEntry(
        index=1,
        session_id="abc12345",
        title="Alpha",
        origin_adapter="telegram",
        tmux_session_name="",
        working_directory=None,
        last_activity=None,
        created_at=None,
        active_agent=None,
        thinking_mode=None,
        tmux_ready=False,
    )
    with pytest.raises(ValueError, match="Session has no tmux session name"):
        telec._resolve_tmux_name(entry)
