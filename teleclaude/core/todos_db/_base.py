"""TodosDb base: connection lifecycle, schema bootstrap, and migrations."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from enum import StrEnum
from pathlib import Path
from typing import cast

import aiosqlite
from instrukt_ai_logging import get_logger
from sqlalchemy import Engine
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session as SqlSession
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.core.db.connection_factory import create_async_db_engine, create_sync_db_engine

from ._schema_bootstrap import bootstrap_todos_db
from ._working_copy import (
    WorkingCopyItemSnapshot,
    WorkingCopyMoveSet,
    all_project_records,
    held_item_ids,
    item_snapshot,
    move_set,
)
from ._write_admission import attach_write_admission, connect_admitted_async

logger = get_logger(__name__)
_SQLITE_BUSY_TIMEOUT_S = 5.0
_BEGIN_IMMEDIATE_SQL = "BEGIN IMMEDIATE"


class StoreSessionEvent(StrEnum):
    """Closed set of SQLAlchemy session events used by the store boundary."""

    BEFORE_COMMIT = "before_commit"
    AFTER_COMMIT = "after_commit"
    AFTER_ROLLBACK = "after_rollback"


def _default_on_mutation(_event_hint: str, _event_data: Mapping[str, object] | None = None) -> None:
    """Default no-op mutation callback."""


def _default_on_phase_transition(
    _slug: str,
    _prior_lifecycle_phase: str,
    _new_lifecycle_phase: str,
    _state_payload: Mapping[str, object],
) -> None:
    """Default no-op phase transition callback."""


def _default_on_delivered(
    _slug: str,
    _delivery_commit: str | None,
    _delivered_at: str,
) -> None:
    """Default no-op delivery callback."""


class TodosDbBase:
    """Database base class for the todos lifecycle store."""

    def __init__(self, db_path: str, *, write_admission_budget: float | None = None) -> None:
        """Open a store; a budget bounds in wall-clock seconds how long a write waits for the writer."""
        self.db_path = db_path
        self._write_admission_budget = write_admission_budget
        self._db_path = Path(db_path)
        self.conn: aiosqlite.Connection | None = None
        self._engine: AsyncEngine | None = None
        self._sync_engine: Engine | None = None
        self._sessionmaker: async_sessionmaker[SqlAsyncSession] | None = None
        self._sync_sessionmaker: sessionmaker[SqlSession] | None = None
        self._before_commit_callback: Callable[[SqlSession], None] | None = None
        self._after_commit_callback: Callable[[SqlSession], None] | None = None
        self._after_rollback_callback: Callable[[SqlSession], None] | None = None
        self._before_commit_listener: Callable[[SqlSession], None] | None = None
        self._after_commit_listener: Callable[[SqlSession], None] | None = None
        self._after_rollback_listener: Callable[[SqlSession], None] | None = None
        self._session_class: type[SqlSession]
        self._session_listeners_registered = False
        self._on_mutation: Callable[[str, Mapping[str, object] | None], None] = _default_on_mutation
        self._on_phase_transition: Callable[[str, str, str, Mapping[str, object]], None] = _default_on_phase_transition
        self._on_delivered: Callable[[str, str | None, str], None] = _default_on_delivered

        class StoreSession(SqlSession):
            """Session class scoped to one store instance's commit seam."""

        def before_commit(session: SqlSession) -> None:
            if session.bind not in (self._sync_engine, self._engine.sync_engine if self._engine else None):
                return
            if self._before_commit_callback is not None:
                session.flush()
                self._before_commit_callback(session)

        def after_commit(session: SqlSession) -> None:
            if session.bind not in (self._sync_engine, self._engine.sync_engine if self._engine else None):
                return
            if self._after_commit_callback is not None:
                self._after_commit_callback(session)

        def after_rollback(session: SqlSession) -> None:
            if session.bind not in (self._sync_engine, self._engine.sync_engine if self._engine else None):
                return
            if self._after_rollback_callback is not None:
                self._after_rollback_callback(session)

        sqlalchemy_event.listen(StoreSession, StoreSessionEvent.BEFORE_COMMIT, before_commit)
        sqlalchemy_event.listen(StoreSession, StoreSessionEvent.AFTER_COMMIT, after_commit)
        sqlalchemy_event.listen(StoreSession, StoreSessionEvent.AFTER_ROLLBACK, after_rollback)
        self._session_class = StoreSession
        self._before_commit_listener = before_commit
        self._after_commit_listener = after_commit
        self._after_rollback_listener = after_rollback
        self._session_listeners_registered = True

    def set_commit_callbacks(
        self,
        before_commit: Callable[[SqlSession], None] | None,
        after_commit: Callable[[SqlSession], None] | None,
        after_rollback: Callable[[SqlSession], None] | None = None,
    ) -> None:
        """Install the optional working-copy commit boundary for this store."""
        self._before_commit_callback = before_commit
        self._after_commit_callback = after_commit
        self._after_rollback_callback = after_rollback

    def on_committed(self, event_hint: str = "todo_updated", event_data: Mapping[str, object] | None = None) -> None:
        """Signal that a caller-managed transaction has committed.

        Use this when the caller owns the session (e.g. multi-step transactions
        in route handlers) and needs to notify the mutation boundary after commit,
        without accessing the protected _on_mutation attribute directly.
        """
        self._on_mutation(event_hint, event_data)

    async def initialize(self) -> None:
        """Bootstrap schema and initialize async + sync runtime access."""
        bootstrap_todos_db(self.db_path)

        self._engine = create_async_db_engine(self.db_path)
        self._sync_engine = create_sync_db_engine(self.db_path)
        self._admit_writes(self._engine.sync_engine)
        self._admit_writes(self._sync_engine)
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=SqlAsyncSession, sync_session_class=self._session_class
        )
        self._sync_sessionmaker = sessionmaker(self._sync_engine, expire_on_commit=False, class_=self._session_class)

        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row

    def initialize_sync(self) -> None:
        """Sync schema bootstrap using the shared factory.

        Also sets up the async engine + sessionmaker so a single instance
        cached by ``get_todos_db_sync`` is fully usable from async callers
        too. Without this, the factory cache becomes order-sensitive:
        sync-first callers leave async runtime fields ``None``, and the
        next async caller gets the same cached instance and fails with
        "TodosDb not initialized" even though the file is on disk.
        """
        bootstrap_todos_db(self.db_path)
        self._sync_engine = create_sync_db_engine(self.db_path)
        self._admit_writes(self._sync_engine)
        self._sync_sessionmaker = sessionmaker(self._sync_engine, expire_on_commit=False, class_=self._session_class)
        if self._engine is None:
            self._engine = create_async_db_engine(self.db_path)
            self._admit_writes(self._engine.sync_engine)
        if self._sessionmaker is None:
            self._sessionmaker = async_sessionmaker(
                self._engine, expire_on_commit=False, class_=SqlAsyncSession, sync_session_class=self._session_class
            )

    def _admit_writes(self, engine: Engine) -> None:
        """Bound this store's wait for the writer when it was opened with an admission budget."""
        if self._write_admission_budget is not None:
            attach_write_admission(engine, self._write_admission_budget)

    def _session(self) -> SqlAsyncSession:
        """Create an async ORM session from the initialized session factory."""
        if self._sessionmaker is None:
            msg = "TodosDb not initialized - call initialize() first"
            raise RuntimeError(msg)
        return self._sessionmaker()

    async def migration_move_set(self) -> WorkingCopyMoveSet:
        """Read typed open-work identities through the store-owned session boundary."""
        async with self._session() as session:
            return await session.run_sync(move_set)

    async def migration_item_snapshot(self, item_id: str) -> WorkingCopyItemSnapshot | None:
        """Read a complete source snapshot, including every artifact version."""
        async with self._session() as session:
            return await session.run_sync(lambda sync_session: item_snapshot(sync_session, item_id))

    async def migration_project_records(self) -> tuple[tuple[str, Mapping[str, object]], ...]:
        """Read the complete typed project-level evidence set."""
        async with self._session() as session:
            return await session.run_sync(all_project_records)

    async def migration_held_item_ids(self) -> frozenset[str]:
        """Read item identities held by this store in any lifecycle status."""
        async with self._session() as session:
            return await session.run_sync(held_item_ids)

    def _sync_session(self) -> SqlSession:
        """Create a sync ORM session from the initialized session factory."""
        if self._sync_sessionmaker is None:
            if self._sync_engine is None:
                self.initialize_sync()
            if self._sync_engine is None:
                msg = "TodosDb sync engine not initialized"
                raise RuntimeError(msg)
            self._sync_sessionmaker = sessionmaker(
                self._sync_engine, expire_on_commit=False, class_=self._session_class
            )
        return self._sync_sessionmaker()

    def _sync_conn(self) -> sqlite3.Connection:
        """Open a shared-factory-backed synchronous DB-API connection."""
        if self._sync_engine is None:
            self.initialize_sync()
        if self._sync_engine is None:
            msg = "TodosDb sync engine not initialized"
            raise RuntimeError(msg)
        raw_connection = self._sync_engine.raw_connection()
        return cast(sqlite3.Connection, raw_connection)

    @asynccontextmanager
    async def hold_write_window(self) -> AsyncIterator[None]:
        """Hold SQLite's writer reservation without committing changes."""
        if self._write_admission_budget is not None:
            connection = await connect_admitted_async(self.db_path, self._write_admission_budget)
        else:
            connection = await aiosqlite.connect(self.db_path, timeout=_SQLITE_BUSY_TIMEOUT_S)
            try:
                await connection.execute(_BEGIN_IMMEDIATE_SQL)
            except BaseException:
                await connection.close()
                raise
        try:
            yield
        finally:
            await connection.rollback()
            await connection.close()

    async def close(self) -> None:
        """Close open runtime resources."""
        if self.conn is not None:
            await self.conn.close()
            self.conn = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
        if self._sync_engine is not None:
            self._sync_engine.dispose()
            self._sync_engine = None
        self._sessionmaker = None
        self._sync_sessionmaker = None
        if self._session_listeners_registered:
            if self._before_commit_listener is not None:
                sqlalchemy_event.remove(
                    self._session_class, StoreSessionEvent.BEFORE_COMMIT, self._before_commit_listener
                )
            if self._after_commit_listener is not None:
                sqlalchemy_event.remove(
                    self._session_class, StoreSessionEvent.AFTER_COMMIT, self._after_commit_listener
                )
            if self._after_rollback_listener is not None:
                sqlalchemy_event.remove(
                    self._session_class, StoreSessionEvent.AFTER_ROLLBACK, self._after_rollback_listener
                )
            self._session_listeners_registered = False
