from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from teleclaude.core.todos_db import TodosDb


@pytest.fixture
async def todos_db(tmp_path: Path) -> AsyncIterator[TodosDb]:
    database = TodosDb(str(tmp_path / "todos.db"))
    await database.initialize()
    if database.conn is not None:
        await database.conn.execute("PRAGMA journal_mode = WAL")
        await database.conn.execute("PRAGMA synchronous = OFF")
    try:
        yield database
    finally:
        await database.close()
