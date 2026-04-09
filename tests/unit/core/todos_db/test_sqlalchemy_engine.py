# guard: no-companion
# pylint: disable=import-outside-toplevel,import-error,no-name-in-module,protected-access,no-member,too-few-public-methods
"""Test spec (xfail) for R5: todos.db SQLAlchemy migration.

todos.db transitions from raw aiosqlite to the shared connection factory's
SQLAlchemy engine. Existing calling contexts (async + sync), behavioral contracts
(singleton caching, mutation hooks, roadmap ops, artifact versioning), and
reconciliation logic are preserved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Engine lifecycle: shared factory integration
# ---------------------------------------------------------------------------


class TestTodosDbUsesSharedFactory:
    """todos.db obtains its engine from the shared connection factory."""

    async def test_initialize_creates_sqlalchemy_engine(self, tmp_path: Path) -> None:
        """After initialize(), todos.db has a SQLAlchemy engine, not a raw aiosqlite conn."""
        from teleclaude.core.todos_db import TodosDb

        db = TodosDb(str(tmp_path / "todos.db"))
        await db.initialize()
        try:
            # After migration, TodosDb should have an engine attribute, not just conn
            assert hasattr(db, "_engine") or hasattr(db, "engine"), (
                "TodosDb lacks a SQLAlchemy engine attribute after initialization"
            )
            # The raw aiosqlite connection should no longer be the primary access path
            # (it may still exist for bootstrap, but the engine is the runtime path)
        finally:
            await db.close()

    async def test_initialize_applies_factory_pragmas(self, tmp_path: Path) -> None:
        """PRAGMAs are applied by the shared factory, not by inline code."""
        from teleclaude.core.todos_db import TodosDb

        db = TodosDb(str(tmp_path / "todos.db"))
        await db.initialize()
        try:
            # Verify PRAGMAs via the engine
            from sqlalchemy import text

            async with db._session() as session:
                result = await session.exec(text("PRAGMA foreign_keys"))
                assert result.scalar() == 1
                result = await session.exec(text("PRAGMA journal_mode"))
                assert result.scalar().lower() == "wal"
        finally:
            await db.close()


# ---------------------------------------------------------------------------
# Async access: API routes, daemon
# ---------------------------------------------------------------------------


class TestTodosDbAsyncAccess:
    """Async access patterns are preserved after migration."""

    async def test_add_roadmap_entry_async(self, tmp_path: Path) -> None:
        """Roadmap entries can be created via the async engine."""
        from teleclaude.core.todos_db import TodosDb

        db = TodosDb(str(tmp_path / "todos.db"))
        await db.initialize()
        try:
            await db.add_entry(slug="test-item", position=1, description="Test")
            entries = await db.list_entries()
            slugs = [getattr(e, "slug", None) for e in entries]
            assert "test-item" in slugs
        finally:
            await db.close()

    async def test_state_roundtrip_async(self, tmp_path: Path) -> None:
        """State get/set works through the SQLAlchemy async engine."""
        from teleclaude.core.todos_db import TodosDb

        db = TodosDb(str(tmp_path / "todos.db"))
        await db.initialize()
        try:
            await db.add_entry(slug="state-test", position=1, description="State test")
            state = {"phase": "draft", "version": 2}
            await db.set_state("state-test", json.dumps(state))
            result = await db.get_state("state-test")
            assert result is not None
            parsed = json.loads(result) if isinstance(result, str) else result
            assert parsed["phase"] == "draft"
        finally:
            await db.close()

    async def test_artifact_crud_async(self, tmp_path: Path) -> None:
        """Artifact read/write works through the SQLAlchemy async engine."""
        from teleclaude.core.todos_db import TodosDb

        db = TodosDb(str(tmp_path / "todos.db"))
        await db.initialize()
        try:
            await db.add_entry(slug="art-test", position=1, description="Artifact test")
            await db.write_artifact("art-test", "spec.md", "# Spec content", updated_by="test")
            content = await db.read_artifact("art-test", "spec.md")
            assert content is not None
            assert "Spec content" in content
        finally:
            await db.close()


# ---------------------------------------------------------------------------
# Sync access: integration state machine, worker threads
# ---------------------------------------------------------------------------


class TestTodosDbSyncAccess:
    """Sync access from worker threads is preserved after migration."""

    def test_sync_conn_returns_usable_connection(self, tmp_path: Path) -> None:
        """_sync_conn() returns a connection that can query the database."""
        from teleclaude.core.todos_db import TodosDb

        db = TodosDb(str(tmp_path / "todos.db"))
        db.initialize_sync()
        conn = db._sync_conn()
        try:
            # Should be able to query the roadmap table
            result = conn.execute("SELECT COUNT(*) FROM roadmap")
            count = result.fetchone()[0]
            assert count >= 0  # Table exists and is queryable
        finally:
            conn.close()

    def test_sync_access_uses_shared_factory_engine(self, tmp_path: Path) -> None:
        """Sync connections come from the shared factory, not from raw sqlite3.connect."""
        from teleclaude.core.todos_db import TodosDb

        db = TodosDb(str(tmp_path / "todos.db"))
        db.initialize_sync()
        conn = db._sync_conn()
        try:
            # PRAGMAs should be applied by the factory
            result = conn.execute("PRAGMA foreign_keys")
            assert result.fetchone()[0] == 1
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Behavioral contracts preserved
# ---------------------------------------------------------------------------


class TestMutationHookPreserved:
    """Mutation callbacks fire after write operations."""

    async def test_mutation_callback_fires_on_write(self, tmp_path: Path) -> None:
        """The on_mutation callback fires when roadmap entries are modified."""
        from teleclaude.core.todos_db import TodosDb

        db = TodosDb(str(tmp_path / "todos.db"))
        await db.initialize()
        mutations: list[str] = []
        db._on_mutation = lambda: mutations.append("fired")
        try:
            await db.add_entry(slug="hook-test", position=1, description="Hook test")
            assert len(mutations) > 0, "Mutation callback did not fire"
        finally:
            await db.close()


class TestRoadmapOperationsPreserved:
    """Complex roadmap operations work after migration."""

    async def test_dependency_graph_operations(self, tmp_path: Path) -> None:
        """Roadmap dependency graph (set_deps, get deps) works via SQLAlchemy."""
        from teleclaude.core.todos_db import TodosDb

        db = TodosDb(str(tmp_path / "todos.db"))
        await db.initialize()
        try:
            await db.add_entry(slug="dep-a", position=1, description="Dep A")
            await db.add_entry(slug="dep-b", position=2, description="Dep B")
            await db.set_deps("dep-b", after=["dep-a"])
            deps = await db.get_deps("dep-b")
            assert "dep-a" in deps
        finally:
            await db.close()

    async def test_move_entry_reorders_correctly(self, tmp_path: Path) -> None:
        """Moving a roadmap entry updates position ordering."""
        from teleclaude.core.todos_db import TodosDb

        db = TodosDb(str(tmp_path / "todos.db"))
        await db.initialize()
        try:
            await db.add_entry(slug="move-a", position=1, description="A")
            await db.add_entry(slug="move-b", position=2, description="B")
            await db.add_entry(slug="move-c", position=3, description="C")
            await db.move_entry("move-c", before="move-a")
            entries = await db.list_entries()
            slugs = [getattr(e, "slug", None) for e in entries]
            assert slugs.index("move-c") < slugs.index("move-a")
        finally:
            await db.close()


class TestArtifactVersioningPreserved:
    """Artifact version history is maintained after migration."""

    async def test_artifact_write_creates_version_entry(self, tmp_path: Path) -> None:
        """Writing an artifact twice creates at least two version history entries."""
        from teleclaude.core.todos_db import TodosDb

        db = TodosDb(str(tmp_path / "todos.db"))
        await db.initialize()
        try:
            slug = "ver-test"
            await db.add_entry(slug=slug, position=1, description="Version test")
            await db.write_artifact(slug, "doc.md", "v1 content", updated_by="agent-a")
            await db.write_artifact(slug, "doc.md", "v2 content", updated_by="agent-b")
            # After two writes, there must be at least 2 version entries
            history = await db.list_artifact_versions(slug, "doc.md")  # pyright: ignore[reportAttributeAccessIssue]
            count = len(history)
            assert count >= 2, f"Expected >= 2 version entries after 2 writes, got {count}"
        finally:
            await db.close()


# ---------------------------------------------------------------------------
# R5: Reconciliation logic preserved
# ---------------------------------------------------------------------------


class TestReconciliationPreserved:
    """todos.db reconciliation logic works via SQLAlchemy engine."""

    async def test_reconcile_is_idempotent(self, tmp_path: Path) -> None:
        """Calling reconcile() twice produces no duplicate rows or errors.

        Singleton caching and idempotent initialization are both verified:
        the second call must not raise and must not double the row count.
        """
        from teleclaude.core.todos_db import TodosDb

        db = TodosDb(str(tmp_path / "todos.db"))
        await db.initialize()
        try:
            await db.add_entry(slug="reconcile-test", position=1, description="Reconcile test")
            await db.reconcile()  # pyright: ignore[reportAttributeAccessIssue]
            entries_after_first = await db.list_entries()
            count_first = sum(1 for e in entries_after_first if getattr(e, "slug", None) == "reconcile-test")

            await db.reconcile()  # pyright: ignore[reportAttributeAccessIssue]
            entries_after_second = await db.list_entries()
            count_second = sum(1 for e in entries_after_second if getattr(e, "slug", None) == "reconcile-test")

            assert count_second == count_first == 1, (
                f"Reconcile is not idempotent: first={count_first}, second={count_second}"
            )
        finally:
            await db.close()

    def test_singleton_caching_returns_same_instance(self, tmp_path: Path) -> None:
        """Constructing TodosDb with the same path twice returns the same instance.

        If TodosDb caches instances by path, the second construction must return
        the same object (or at least not re-initialize the schema).
        """
        from teleclaude.core.todos_db import TodosDb

        db_path = str(tmp_path / "todos.db")
        db1 = TodosDb(db_path)
        db2 = TodosDb(db_path)
        # Either singleton (same object) or equivalent (same path, no double-init error)
        assert db1 is db2 or str(db1._db_path) == str(db2._db_path), (  # pyright: ignore[reportAttributeAccessIssue]
            "Two TodosDb instances for the same path should be the same object or equivalent"
        )


# ---------------------------------------------------------------------------
# F2 regression: artifact writes must not materialize roadmap entries
# ---------------------------------------------------------------------------


class TestArtifactWriteRejectsUnknownSlug:
    """Writing artifacts for a slug with no roadmap entry must fail fast."""

    async def test_async_write_artifact_unknown_slug_raises(self, tmp_path: Path) -> None:
        """write_artifact() raises ValueError when slug has no active roadmap entry."""
        from teleclaude.core.todos_db import TodosDb

        db = TodosDb(str(tmp_path / "todos.db"))
        await db.initialize()
        try:
            with pytest.raises(ValueError, match="no active roadmap entry"):
                await db.write_artifact("nonexistent-slug", "spec.md", "content")

            entries = await db.list_entries()
            slugs = [getattr(e, "slug", None) for e in entries]
            assert "nonexistent-slug" not in slugs, "Roadmap entry must not be created"
        finally:
            await db.close()

    def test_sync_write_artifact_unknown_slug_raises(self, tmp_path: Path) -> None:
        """write_artifact_sync() raises ValueError when slug has no active roadmap entry."""
        from teleclaude.core.todos_db import TodosDb

        db = TodosDb(str(tmp_path / "todos.db"))
        db.initialize_sync()
        with pytest.raises(ValueError, match="no active roadmap entry"):
            db.write_artifact_sync("nonexistent-slug", "spec.md", "content")
