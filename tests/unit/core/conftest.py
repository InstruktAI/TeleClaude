"""Conftest for tests/unit/core — sets TELECLAUDE_CONFIG_PATH before db.py loads.

tests/unit/conftest.py overrides _isolate_test_environment with a no-op (no DB
access assumed).  Tests in this package DO import teleclaude.core.db for static
method testing, so they need a valid config path before the module is imported.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from teleclaude.core.todos_db import TodosDb

# Ensure test config path is set (respects CI env var if already set).
# This must run at module-import time (before any test imports db.py).
_worktree_root = Path(__file__).resolve().parents[3]
os.environ.setdefault("TELECLAUDE_CONFIG_PATH", str(_worktree_root / "tests" / "integration" / "config.yml"))


@pytest.fixture
async def todos_db(tmp_path: Path) -> AsyncIterator[TodosDb]:
    """Real TodosDb backed by a temporary SQLite database."""
    database = TodosDb(str(tmp_path / "todos.db"))
    await database.initialize()
    if database.conn is not None:
        await database.conn.execute("PRAGMA journal_mode = WAL")
        await database.conn.execute("PRAGMA synchronous = OFF")
    try:
        yield database
    finally:
        await database.close()
