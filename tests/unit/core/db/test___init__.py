"""Targeted tests for the get_db factory and read_agent_availability_sync helper."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import teleclaude.core.db as db_pkg
from teleclaude.core.db import Db, get_db, read_agent_availability_sync


@pytest.mark.asyncio
async def test_get_db_returns_initialized_singleton(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """get_db hands out an initialized Db whose first call performs the bootstrap."""
    fresh = Db(str(tmp_path / "teleclaude.db"))
    monkeypatch.setattr(db_pkg, "db", fresh)
    assert not fresh.is_initialized()

    handed_out = await get_db()
    assert handed_out is fresh
    assert fresh.is_initialized()

    again = await get_db()
    assert again is fresh

    await fresh.close()


def test_read_agent_availability_sync_treats_missing_db_as_available(tmp_path: Path) -> None:
    """Fail-open semantics: cold sub-CLI without a DB file proceeds."""
    missing = tmp_path / "no.db"
    assert read_agent_availability_sync(str(missing), "claude") is True


def test_read_agent_availability_sync_treats_missing_table_as_available(tmp_path: Path) -> None:
    """Fail-open semantics: schema not yet bootstrapped means no exclusion."""
    db_path = tmp_path / "teleclaude.db"
    sqlite3.connect(str(db_path)).close()
    assert read_agent_availability_sync(str(db_path), "claude") is True


def _seed_availability(
    db_path: Path,
    *,
    available: int,
    unavailable_until: str | None,
    degraded_until: str | None,
    reason: str | None,
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE agent_availability ("  # guard: raw-sql
        "agent TEXT PRIMARY KEY, available INTEGER, unavailable_until TEXT, "
        "reason TEXT, degraded_until TEXT)"
    )
    conn.execute(
        "INSERT INTO agent_availability (agent, available, unavailable_until, reason, degraded_until) "  # guard: raw-sql
        "VALUES (?, ?, ?, ?, ?)",
        ("claude", available, unavailable_until, reason, degraded_until),
    )
    conn.commit()
    conn.close()


def test_read_agent_availability_sync_unavailable_until_in_future_excludes(tmp_path: Path) -> None:
    db_path = tmp_path / "teleclaude.db"
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    _seed_availability(db_path, available=0, unavailable_until=future, degraded_until=None, reason=None)
    assert read_agent_availability_sync(str(db_path), "claude") is False


def test_read_agent_availability_sync_unavailable_until_expired_overrides(tmp_path: Path) -> None:
    """Expired unavailable_until restores availability even when the flag is 0."""
    db_path = tmp_path / "teleclaude.db"
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    _seed_availability(db_path, available=0, unavailable_until=past, degraded_until=None, reason=None)
    assert read_agent_availability_sync(str(db_path), "claude") is True


def test_read_agent_availability_sync_degraded_in_window_excludes(tmp_path: Path) -> None:
    db_path = tmp_path / "teleclaude.db"
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    _seed_availability(db_path, available=1, unavailable_until=None, degraded_until=future, reason="degraded:rate")
    assert read_agent_availability_sync(str(db_path), "claude") is False


def test_read_agent_availability_sync_degraded_after_ttl_recovers(tmp_path: Path) -> None:
    """Expired degraded_until lets the agent return to dispatch eligibility."""
    db_path = tmp_path / "teleclaude.db"
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    _seed_availability(db_path, available=1, unavailable_until=None, degraded_until=past, reason="degraded:rate")
    assert read_agent_availability_sync(str(db_path), "claude") is True
