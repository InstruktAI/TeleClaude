# guard: no-companion
# pylint: disable=import-outside-toplevel,import-error,no-name-in-module,too-few-public-methods,use-implicit-booleaness-not-comparison
"""Test spec (xfail) for R6: mirrors.db SQLAlchemy migration.

mirrors.db transitions from raw sync sqlite3 to the shared connection factory's
sync SQLAlchemy engine. The sync calling context, FTS5 search, read-only patterns,
tombstone tracking, and schema initialization are preserved.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from teleclaude.mirrors import store
from teleclaude.mirrors.store import (
    MirrorRecord,
    MirrorSearchResult,
    MirrorTombstoneRecord,
    delete_mirror_tombstone,
    get_mirror,
    get_mirror_tombstone,
    list_mirrors,
    search_mirrors,
    upsert_mirror,
    upsert_mirror_tombstone,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Engine lifecycle: shared factory integration
# ---------------------------------------------------------------------------


class TestMirrorsUsesSharedFactory:
    """mirrors/store.py obtains connections from the shared connection factory."""

    def test_connect_rw_uses_factory_engine(self) -> None:
        """_connect_rw uses the shared factory instead of raw sqlite3.connect."""
        source_path = Path(store.__file__)
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # After migration, _connect_rw should use the shared factory
        # and not call sqlite3.connect directly.
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_connect_rw":
                found = True
                body_source = ast.unparse(node)
                assert "sqlite3.connect" not in body_source, "_connect_rw still uses raw sqlite3.connect"
                break
        assert found, "_connect_rw not found in mirrors/store.py — may have been renamed or removed"

    def test_connect_ro_uses_factory_engine(self) -> None:
        """_connect_ro uses the shared factory for read-only connections."""
        source_path = Path(store.__file__)
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_connect_ro":
                found = True
                body_source = ast.unparse(node)
                assert "sqlite3.connect" not in body_source, "_connect_ro still uses raw sqlite3.connect"
                break
        assert found, "_connect_ro not found in mirrors/store.py — may have been renamed or removed"


# ---------------------------------------------------------------------------
# FTS5 preservation
# ---------------------------------------------------------------------------


class TestFts5SearchPreserved:
    """FTS5 full-text search works after the SQLAlchemy migration."""

    def test_search_mirrors_returns_fts_results(self, tmp_path: Path) -> None:
        """FTS5 MATCH queries work through the SQLAlchemy engine."""
        db_path = tmp_path / "mirrors.db"

        # Insert a record
        record = MirrorRecord(
            session_id="sess-fts-001",
            source_identity="claude:native-001",
            computer="test-mac",
            agent="claude",
            project="test-project",
            title="SQLAlchemy migration discussion",
            timestamp_start="2026-04-03T12:00:00Z",
            timestamp_end=None,
            conversation_text="We discussed the SQLAlchemy migration for the database layer",
            message_count=5,
            metadata={},
            created_at="2026-04-03T12:00:00Z",
            updated_at="2026-04-03T12:30:00Z",
        )
        upsert_mirror(record, db=str(db_path))

        # Search should find it via FTS
        results = search_mirrors("SQLAlchemy migration", ["claude"], db=str(db_path))
        assert len(results) >= 1
        assert results[0].session_id == "sess-fts-001"

    def test_fts_trigger_sync_on_update(self, tmp_path: Path) -> None:
        """FTS content-sync triggers fire correctly after upsert via SQLAlchemy."""
        db_path = tmp_path / "mirrors.db"

        record = MirrorRecord(
            session_id="sess-fts-002",
            source_identity="claude:native-002",
            computer="test-mac",
            agent="claude",
            project="test-project",
            title="Original title",
            timestamp_start="2026-04-03T12:00:00Z",
            timestamp_end=None,
            conversation_text="Original content about databases",
            message_count=3,
            metadata={},
            created_at="2026-04-03T12:00:00Z",
            updated_at="2026-04-03T12:30:00Z",
        )
        upsert_mirror(record, db=str(db_path))

        # Update the record with new content
        updated_record = MirrorRecord(
            session_id="sess-fts-002",
            source_identity="claude:native-002",
            computer="test-mac",
            agent="claude",
            project="test-project",
            title="Updated title about performance",
            timestamp_start="2026-04-03T12:00:00Z",
            timestamp_end=None,
            conversation_text="Updated content about performance optimization",
            message_count=5,
            metadata={},
            created_at="2026-04-03T12:00:00Z",
            updated_at="2026-04-03T13:00:00Z",
        )
        upsert_mirror(updated_record, db=str(db_path))

        # Old content should not match
        old_results = search_mirrors("Original content", ["claude"], db=str(db_path))
        assert not old_results or all(r.session_id != "sess-fts-002" for r in old_results)

        # New content should match
        new_results = search_mirrors("performance optimization", ["claude"], db=str(db_path))
        assert len(new_results) >= 1
        assert new_results[0].session_id == "sess-fts-002"


# ---------------------------------------------------------------------------
# Typed results: dataclass return types
# ---------------------------------------------------------------------------


class TestMirrorsTypedResults:
    """Mirror queries return typed dataclasses, not raw sqlite3.Row."""

    def test_get_mirror_returns_mirror_record(self, tmp_path: Path) -> None:
        """get_mirror returns a MirrorRecord instance."""
        db_path = tmp_path / "mirrors.db"
        record = MirrorRecord(
            session_id="sess-typed-001",
            source_identity="claude:typed-001",
            computer="test-mac",
            agent="claude",
            project="test-project",
            title="Typed result test",
            timestamp_start=None,
            timestamp_end=None,
            conversation_text="test content",
            message_count=1,
            metadata={},
            created_at="2026-04-03T12:00:00Z",
            updated_at="2026-04-03T12:00:00Z",
        )
        upsert_mirror(record, db=str(db_path))

        result = get_mirror(
            session_id="sess-typed-001",
            db=str(db_path),
        )
        assert result is not None
        assert isinstance(result, MirrorRecord)
        assert result.session_id == "sess-typed-001"

    def test_search_returns_mirror_search_results(self, tmp_path: Path) -> None:
        """search_mirrors returns MirrorSearchResult instances."""
        db_path = tmp_path / "mirrors.db"
        record = MirrorRecord(
            session_id="sess-sr-001",
            source_identity="claude:sr-001",
            computer="test-mac",
            agent="claude",
            project="test-project",
            title="Search result typing",
            timestamp_start=None,
            timestamp_end=None,
            conversation_text="Verifying search result types",
            message_count=1,
            metadata={},
            created_at="2026-04-03T12:00:00Z",
            updated_at="2026-04-03T12:00:00Z",
        )
        upsert_mirror(record, db=str(db_path))

        results = search_mirrors("search result types", ["claude"], db=str(db_path))
        assert len(results) >= 1
        assert isinstance(results[0], MirrorSearchResult)


# ---------------------------------------------------------------------------
# Read-only pattern preservation
# ---------------------------------------------------------------------------


class TestReadOnlyPatternPreserved:
    """Read-only connection patterns still work after migration."""

    def test_list_mirrors_uses_read_connection(self, tmp_path: Path) -> None:
        """list_mirrors can operate with a read-only engine/connection."""
        db_path = tmp_path / "mirrors.db"
        record = MirrorRecord(
            session_id="sess-ro-001",
            source_identity="claude:ro-001",
            computer="test-mac",
            agent="claude",
            project="test-project",
            title="Read-only test",
            timestamp_start=None,
            timestamp_end=None,
            conversation_text="test",
            message_count=1,
            metadata={},
            created_at="2026-04-03T12:00:00Z",
            updated_at="2026-04-03T12:00:00Z",
        )
        upsert_mirror(record, db=str(db_path))

        results = list_mirrors(db=str(db_path))
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# Tombstone operations preserved
# ---------------------------------------------------------------------------


class TestTombstoneOperationsPreserved:
    """Tombstone CRUD works through the SQLAlchemy engine."""

    def test_tombstone_upsert_and_fetch(self, tmp_path: Path) -> None:
        """Tombstones can be created and queried via the migrated engine."""
        db_path = tmp_path / "mirrors.db"
        tombstone = MirrorTombstoneRecord(
            source_identity="claude:tomb-001",
            agent="claude",
            transcript_path="/transcripts/empty.jsonl",
            file_size=0,
            file_mtime="2026-04-03T12:00:00Z",
            created_at="2026-04-03T12:00:00Z",
        )
        upsert_mirror_tombstone(tombstone, db=str(db_path))

        result = get_mirror_tombstone("claude:tomb-001", db=str(db_path))
        assert result is not None
        assert isinstance(result, MirrorTombstoneRecord)
        assert result.source_identity == "claude:tomb-001"

    def test_tombstone_delete(self, tmp_path: Path) -> None:
        """Tombstones can be deleted via the migrated engine."""
        db_path = tmp_path / "mirrors.db"
        tombstone = MirrorTombstoneRecord(
            source_identity="claude:tomb-del",
            agent="claude",
            transcript_path="/transcripts/empty.jsonl",
            file_size=0,
            file_mtime="2026-04-03T12:00:00Z",
            created_at="2026-04-03T12:00:00Z",
        )
        upsert_mirror_tombstone(tombstone, db=str(db_path))
        delete_mirror_tombstone("claude:tomb-del", db=str(db_path))

        result = get_mirror_tombstone("claude:tomb-del", db=str(db_path))
        assert result is None


# ---------------------------------------------------------------------------
# Schema initialization preserved
# ---------------------------------------------------------------------------


class TestSchemaInitPreserved:
    """Schema creation and column migration work via SQLAlchemy."""

    def test_mirrors_table_created_on_first_access(self, tmp_path: Path) -> None:
        """Accessing a fresh database creates the mirrors table and FTS index."""
        db_path = tmp_path / "mirrors.db"
        # This should trigger schema initialization
        results = list_mirrors(db=str(db_path))
        assert results == []

        # Verify tables exist
        conn = sqlite3.connect(str(db_path))
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow')").fetchall()
        }
        conn.close()
        assert "mirrors" in tables
        assert "mirror_tombstones" in tables
