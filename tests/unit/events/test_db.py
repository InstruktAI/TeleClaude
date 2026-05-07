"""Targeted tests for the get_event_db factory lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

import teleclaude.events.db as event_db_module
from teleclaude.events import EventDB, get_event_db


@pytest.fixture(autouse=True)
def isolate_event_db_singleton(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Force the factory to build into a tmp directory and start with no cache."""
    monkeypatch.setattr(event_db_module, "EVENTS_DB_PATH", tmp_path / "events.db")
    monkeypatch.setattr(event_db_module, "_event_db_instance", None)


@pytest.mark.asyncio
async def test_get_event_db_returns_initialized_singleton(tmp_path: Path) -> None:
    first = await get_event_db()
    assert isinstance(first, EventDB)
    assert first.is_initialized()
    # Isolation invariant: the factory honors the monkeypatched EVENTS_DB_PATH
    # (defaults must resolve at call time, not at import time).
    assert first._db_path == (tmp_path / "events.db").expanduser()
    second = await get_event_db()
    assert second is first
    await first.close()


@pytest.mark.asyncio
async def test_get_event_db_replaces_closed_cached_instance() -> None:
    """A closed instance must not be handed out as if initialized."""
    first = await get_event_db()
    await first.close()
    assert not first.is_initialized()
    second = await get_event_db()
    assert second is not first
    assert second.is_initialized()
    await second.close()


@pytest.mark.asyncio
async def test_close_clears_factory_cache() -> None:
    """EventDB.close resets the singleton so the next get_event_db rebuilds."""
    first = await get_event_db()
    await first.close()
    assert event_db_module._event_db_instance is None
