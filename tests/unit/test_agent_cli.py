import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from teleclaude.helpers import agent_cli
from teleclaude.helpers.agent_types import AgentName


def _write_agent_availability_db(
    db_path: str,
    rows: list[tuple[str, int, str | None]],
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_availability (
                agent TEXT PRIMARY KEY,
                available INTEGER DEFAULT 1,
                unavailable_until TEXT,
                reason TEXT
            )
            """
        )
        conn.executemany(
            "INSERT OR REPLACE INTO agent_availability(agent, available, unavailable_until, reason) VALUES (?, ?, ?, ?)",
            [(agent, available, unavailable_until, "test") for agent, available, unavailable_until in rows],
        )
        conn.commit()


def _set_binary_map(monkeypatch: pytest.MonkeyPatch, available: set[str]) -> None:
    monkeypatch.setattr(agent_cli, "resolve_agent_binary", lambda name: name)
    monkeypatch.setattr(
        agent_cli.shutil,
        "which",
        lambda binary: f"/usr/bin/{binary}" if binary in available else None,
    )


def test_pick_agent_prefers_first_db_available(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(agent_cli, "_REPO_ROOT", tmp_path)
    _set_binary_map(monkeypatch, {"claude", "codex", "gemini"})

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    _write_agent_availability_db(
        str(tmp_path / "teleclaude.db"),
        [
            ("claude", 0, future),  # unavailable
            ("codex", 1, None),  # available
        ],
    )

    selected = agent_cli._pick_agent(None)
    assert selected == AgentName.CODEX


def test_pick_agent_rejects_unavailable_preferred(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(agent_cli, "_REPO_ROOT", tmp_path)
    _set_binary_map(monkeypatch, {"claude", "codex", "gemini"})

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    _write_agent_availability_db(
        str(tmp_path / "teleclaude.db"),
        [
            ("codex", 0, future),
        ],
    )

    with pytest.raises(SystemExit, match="marked unavailable"):
        agent_cli._pick_agent(AgentName.CODEX)


def test_pick_agent_treats_expired_unavailability_as_available(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(agent_cli, "_REPO_ROOT", tmp_path)
    _set_binary_map(monkeypatch, {"claude", "codex", "gemini"})

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    _write_agent_availability_db(
        str(tmp_path / "teleclaude.db"),
        [
            ("claude", 0, past),  # expired unavailability
        ],
    )

    selected = agent_cli._pick_agent(None)
    assert selected == AgentName.CLAUDE


def test_pick_agent_fails_when_no_binary_and_db_available(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(agent_cli, "_REPO_ROOT", tmp_path)
    _set_binary_map(monkeypatch, set())

    with pytest.raises(SystemExit, match="no available agent CLI found"):
        agent_cli._pick_agent(None)


def test_pick_agent_skips_degraded(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(agent_cli, "_REPO_ROOT", tmp_path)
    _set_binary_map(monkeypatch, {"claude", "codex", "gemini"})

    with sqlite3.connect(str(tmp_path / "teleclaude.db")) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_availability (
                agent TEXT PRIMARY KEY,
                available INTEGER DEFAULT 1,
                unavailable_until TEXT,
                reason TEXT
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO agent_availability(agent, available, unavailable_until, reason) VALUES (?, ?, ?, ?)",
            ("claude", 1, None, "degraded:manual"),
        )
        conn.commit()

    selected = agent_cli._pick_agent(None)
    assert selected == AgentName.CODEX


def test_pick_agent_rejects_degraded_preferred(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(agent_cli, "_REPO_ROOT", tmp_path)
    _set_binary_map(monkeypatch, {"claude", "codex", "gemini"})

    with sqlite3.connect(str(tmp_path / "teleclaude.db")) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_availability (
                agent TEXT PRIMARY KEY,
                available INTEGER DEFAULT 1,
                unavailable_until TEXT,
                reason TEXT
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO agent_availability(agent, available, unavailable_until, reason) VALUES (?, ?, ?, ?)",
            ("codex", 1, None, "degraded:test"),
        )
        conn.commit()

    with pytest.raises(SystemExit, match="unavailable or degraded"):
        agent_cli._pick_agent(AgentName.CODEX)
