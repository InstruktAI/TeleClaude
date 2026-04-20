# guard: no-companion
# pylint: disable=import-outside-toplevel,import-error,no-name-in-module,too-few-public-methods,use-implicit-booleaness-not-comparison
"""Test spec (xfail) for R1: shared connection factory + R7: PRAGMA consolidation.

All tests are marked xfail — they document the behavioral contract and fail
cleanly before implementation. Remove ``pytestmark`` once implementation passes.

The shared connection factory is the single source of SQLAlchemy engines for all
four databases. It configures PRAGMAs identically via connection-level events and
accepts per-database overrides for pool strategy, pool size, etc.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING, TypedDict

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from teleclaude.core.db._base import DbBase
from teleclaude.core.db.connection_factory import (
    create_async_db_engine,
    create_sync_db_engine,
)
from teleclaude.core.todos_db._base import TodosDbBase
from teleclaude.hooks.receiver import _session
from teleclaude.mirrors import store

pytestmark = [pytest.mark.unit]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


class _PragmaValues(TypedDict):
    """Typed PRAGMA values read back from a SQLite connection."""

    journal_mode: object
    synchronous: object
    busy_timeout: object
    foreign_keys: object
    cache_size: object


async def _read_async_pragmas(engine: AsyncEngine) -> _PragmaValues:
    """Read the PRAGMA baseline through a real async session."""
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            return {
                "journal_mode": (await session.execute(text("PRAGMA journal_mode"))).scalar(),
                "synchronous": (await session.execute(text("PRAGMA synchronous"))).scalar(),
                "busy_timeout": (await session.execute(text("PRAGMA busy_timeout"))).scalar(),
                "foreign_keys": (await session.execute(text("PRAGMA foreign_keys"))).scalar(),
                "cache_size": (await session.execute(text("PRAGMA cache_size"))).scalar(),
            }
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# R1: Shared connection factory produces engines with identical PRAGMA baseline
# ---------------------------------------------------------------------------


class TestConnectionFactoryPragmaBaseline:
    """Every engine from the factory applies the full PRAGMA set on connect."""

    async def test_async_engine_sets_wal_mode(self, tmp_path: Path) -> None:
        """Async engine connections report journal_mode=wal."""
        engine = create_async_db_engine(tmp_path / "test.db")
        pragmas = await _read_async_pragmas(engine)
        assert str(pragmas["journal_mode"]).lower() == "wal"

    async def test_async_engine_sets_synchronous_normal(self, tmp_path: Path) -> None:
        """Async engine connections set synchronous=NORMAL (1)."""
        engine = create_async_db_engine(tmp_path / "test.db")
        pragmas = await _read_async_pragmas(engine)
        assert pragmas["synchronous"] == 1  # NORMAL

    async def test_async_engine_sets_busy_timeout(self, tmp_path: Path) -> None:
        """Async engine connections set busy_timeout=5000."""
        engine = create_async_db_engine(tmp_path / "test.db")
        pragmas = await _read_async_pragmas(engine)
        assert pragmas["busy_timeout"] == 5000

    async def test_async_engine_sets_foreign_keys_on(self, tmp_path: Path) -> None:
        """Async engine connections enable foreign_keys (R1 adds this to teleclaude.db)."""
        engine = create_async_db_engine(tmp_path / "test.db")
        pragmas = await _read_async_pragmas(engine)
        assert pragmas["foreign_keys"] == 1

    async def test_async_engine_sets_cache_size(self, tmp_path: Path) -> None:
        """Async engine connections set cache_size=-8000 (8MB)."""
        engine = create_async_db_engine(tmp_path / "test.db")
        pragmas = await _read_async_pragmas(engine)
        assert pragmas["cache_size"] == -8000

    def test_sync_engine_sets_identical_pragmas(self, tmp_path: Path) -> None:
        """Sync engine connections get the same PRAGMA set as async engines."""
        engine = create_sync_db_engine(tmp_path / "test.db")
        with engine.connect() as conn:
            pragmas = {
                "journal_mode": conn.exec_driver_sql("PRAGMA journal_mode").scalar(),
                "synchronous": conn.exec_driver_sql("PRAGMA synchronous").scalar(),
                "busy_timeout": conn.exec_driver_sql("PRAGMA busy_timeout").scalar(),
                "foreign_keys": conn.exec_driver_sql("PRAGMA foreign_keys").scalar(),
                "cache_size": conn.exec_driver_sql("PRAGMA cache_size").scalar(),
            }
        assert pragmas == {
            "journal_mode": "wal",
            "synchronous": 1,
            "busy_timeout": 5000,
            "foreign_keys": 1,
            "cache_size": -8000,
        }


class TestConnectionFactoryAsyncPragmaPath:
    """Async PRAGMA configuration is verified through a real async connection."""

    async def test_async_connection_sets_full_pragma_baseline(self, tmp_path: Path) -> None:
        """Opening an async connection applies the full PRAGMA baseline.

        The existing sync-path tests verify the sync event listeners fire.
        This test exercises the async path to confirm PRAGMAs are applied
        on async connections, not just via engine.sync_engine.connect().
        """
        engine = create_async_db_engine(tmp_path / "async_pragma.db")
        pragmas = await _read_async_pragmas(engine)

        assert str(pragmas["journal_mode"]).lower() == "wal"
        assert pragmas["synchronous"] == 1
        assert pragmas["busy_timeout"] == 5000
        assert pragmas["foreign_keys"] == 1
        assert pragmas["cache_size"] == -8000


class TestConnectionFactoryOverrides:
    """Per-database overrides are applied while preserving the PRAGMA baseline."""

    def test_custom_pool_class_accepted(self, tmp_path: Path) -> None:
        """Factory accepts poolclass override without breaking PRAGMAs."""
        engine = create_sync_db_engine(tmp_path / "test.db", poolclass=StaticPool)
        with engine.connect() as conn:
            result = conn.exec_driver_sql("PRAGMA journal_mode")
            assert result.scalar().lower() == "wal"

    async def test_custom_pool_size_accepted(self, tmp_path: Path) -> None:
        """Factory accepts pool_size override."""
        engine = create_async_db_engine(tmp_path / "test.db", pool_size=5)
        pragmas = await _read_async_pragmas(engine)
        assert str(pragmas["journal_mode"]).lower() == "wal"


class TestConnectionFactoryEngineTypes:
    """Factory produces correctly typed engines for async and sync contexts."""

    def test_async_engine_is_async_engine_type(self, tmp_path: Path) -> None:
        """create_async_db_engine returns an AsyncEngine."""
        engine = create_async_db_engine(tmp_path / "test.db")
        assert isinstance(engine, AsyncEngine)

    def test_sync_engine_is_engine_type(self, tmp_path: Path) -> None:
        """create_sync_db_engine returns a sync Engine."""
        engine = create_sync_db_engine(tmp_path / "test.db")
        assert isinstance(engine, Engine)


# ---------------------------------------------------------------------------
# R7: No manual PRAGMA setting outside the shared connection factory
# ---------------------------------------------------------------------------


class TestPragmaConsolidation:
    """After migration, PRAGMA configuration exists only in the factory."""

    def test_teleclaude_db_init_uses_factory(self) -> None:
        """DbBase.initialize() obtains its engine from the shared factory,
        not from a local create_async_engine call with inline PRAGMAs.
        """
        source = inspect.getsource(DbBase.initialize)
        tree = ast.parse(dedent(source))
        # No direct PRAGMA execution in initialize (cursor.execute/conn.execute with PRAGMA)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "PRAGMA" not in node.value.upper() or "wal_checkpoint" in node.value.lower(), (
                    f"Found manual PRAGMA in DbBase.initialize: {node.value}"
                )

    def test_todos_db_init_uses_factory(self) -> None:
        """TodosDbBase.initialize() obtains its engine from the shared factory."""
        source = inspect.getsource(TodosDbBase.initialize)
        tree = ast.parse(dedent(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "PRAGMA" not in node.value.upper(), (
                    f"Found manual PRAGMA in TodosDbBase.initialize: {node.value}"
                )

    def test_mirrors_store_uses_factory(self) -> None:
        """mirrors/store.py connection helpers use the shared factory, not inline PRAGMAs."""
        source_path = Path(store.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        pragma_calls: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "PRAGMA" in node.value.upper() and "wal_checkpoint" not in node.value.lower():
                    pragma_calls.append(node.value)
        assert pragma_calls == [], f"Found manual PRAGMA calls in mirrors/store.py: {pragma_calls}"

    def test_receiver_session_uses_factory(self) -> None:
        """Hook receiver _create_sync_engine uses the shared factory."""
        source_path = Path(_session.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        pragma_calls: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "PRAGMA" in node.value.upper():
                    pragma_calls.append(node.value)
        assert pragma_calls == [], f"Found manual PRAGMA calls in receiver/_session.py: {pragma_calls}"


class TestAllDatabasesPragmaConsistency:
    """Integration-style: all four databases report identical PRAGMA values at runtime."""

    @pytest.mark.parametrize(
        "db_name",
        ["teleclaude", "todos", "mirrors", "outbox"],
    )
    def test_pragma_values_match_baseline(self, tmp_path: Path, db_name: str) -> None:
        """Each database engine reports the canonical PRAGMA baseline."""
        db_path = tmp_path / f"{db_name}.db"
        engine = create_sync_db_engine(db_path)
        with engine.connect() as conn:
            journal = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
            sync = conn.exec_driver_sql("PRAGMA synchronous").scalar()
            timeout = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
            fk = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
            cache = conn.exec_driver_sql("PRAGMA cache_size").scalar()

        assert journal.lower() == "wal", f"{db_name}: journal_mode"
        assert sync == 1, f"{db_name}: synchronous"
        assert timeout == 5000, f"{db_name}: busy_timeout"
        assert fk == 1, f"{db_name}: foreign_keys"
        assert cache == -8000, f"{db_name}: cache_size"
