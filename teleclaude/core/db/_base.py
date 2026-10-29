"""Database base class: lifecycle, static helpers, and shared infrastructure."""

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite
from instrukt_ai_logging import get_logger
from sqlalchemy import and_, or_, text  # guard: raw-sql
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import DB_IN_MEMORY
from teleclaude.core.migration_signal import MigrationStore
from teleclaude.core.migrations.runner import MIGRATIONS_DIR, baseline_migrations, run_pending_migrations
from teleclaude.paths import EVENTS_DB_PATH
from teleclaude.project_root import is_slug_worktree, resolve_invocation_roots

from .. import db_models
from ..dates import ensure_utc, parse_iso_datetime
from ..models import Session, decode_relay_exchange
from ..models._session import SessionField
from ..models._types import JsonDict, to_json_dict
from ..session_status import AgentStatusReason, AgentStatusValue
from ._agent_status import decode_open_tool_calls, decode_turn_notifications
from .connection_factory import create_async_db_engine, get_outbox_db_path
from .stores import STORES, DaemonStore, store_db_path

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

DB_NOT_INITIALIZED_ERROR = "Database not initialized - call initialize() first"
CORE_SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"
_USER_TABLE_COUNT_SQL = "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"

RUNTIME_COMPACTION_MIN_FREELIST_RATIO = 0.20
RUNTIME_COMPACTION_MIN_FREE_BYTES = 16 * 1024 * 1024

_MIGRATION_WORKTREE_SKIP_MESSAGE = (
    "Skipping pending-migration application for %s: invoked from a todo worktree "
    "against an already-existing database. A worktree's own migration files are "
    "not yet part of the deployed daemon and must never execute against shared, "
    "already-populated data ahead of it; the canonical checkout (or the daemon "
    "itself) applies them once merged."
)

_WORKTREE_BOOTSTRAP_REFUSAL_TEMPLATE = (
    "%s does not exist yet, and this process is invoked from a todo worktree. "
    "Creating the shared daemon database for the first time is a canonical-"
    "checkout or daemon-owned act: baselining it here would permanently record "
    "this worktree's own undelivered migrations as applied without ever running "
    "their data transformations. Start the daemon (`make start`) or run this "
    "from the canonical checkout instead."
)


class WorktreeDatabaseBootstrapRefused(RuntimeError):
    """A todo-worktree process attempted to create a shared daemon database from empty.

    Distinct from the pending-migration skip below: that case protects an
    already-existing database from having an undelivered migration's SQL
    executed against it. This case is the one no branch of that guard can
    reconcile — baselining a brand-new database always records the *complete*
    current migration set as applied, including any migration whose real job
    is a data transformation (not just a schema change). Recording such a
    migration as applied without ever running it makes that transformation
    permanently disappear for every row created before the canonical merge.
    The only door that closes for every migration shape, schema or data
    alike, is refusing to be the one who creates this database at all: a
    worktree is never the owner of a shared daemon database's genesis.
    """


def _invoked_from_slug_worktree() -> bool:
    """Return whether the current process's invocation root is a todo worktree.

    Two migration operations are gated by this check, for related but
    distinct reasons. ``run_pending_migrations`` executes each unapplied
    migration's SQL against whatever rows are already on disk, so running it
    from a worktree would apply an undelivered migration to shared,
    already-populated production data ahead of the code that owns it. Creating
    the database from empty (and therefore calling ``baseline_migrations``) is
    gated for a different reason: baselining does not execute anything, but it
    does permanently record every current migration — including ones whose
    real effect is a data transformation, not a schema change — as already
    applied. A worktree's migration set is not yet canonical, so a worktree
    must never be the one to create this database in the first place; that is
    a canonical-checkout or daemon-owned act. Detection failure (no resolvable
    git root — an isolated test fixture, for instance) is not itself worktree
    evidence, so it falls through to the pre-existing, unguarded behavior
    rather than blocking it.
    """
    try:
        return is_slug_worktree(resolve_invocation_roots().repository_root)
    except (OSError, FileNotFoundError, RuntimeError):
        return False


def _create_runtime_engine(db_path: str | Path, *, pooled: bool) -> AsyncEngine:
    """Create the runtime engine for one daemon database file.

    A throwaway in-memory database set (tests) pins a single reused connection per file; on-disk
    databases use the SQLite dialect's pooled default.
    """
    if pooled:
        return create_async_db_engine(db_path)
    return create_async_db_engine(db_path, poolclass=StaticPool)


@dataclass(frozen=True)
class SqliteDatabaseStats:
    """SQLite file-size statistics used by runtime compaction decisions."""

    page_count: int
    freelist_count: int
    page_size: int

    @property
    def freelist_ratio(self) -> float:
        """Return the fraction of allocated pages currently on the freelist."""
        if self.page_count <= 0:
            return 0.0
        return self.freelist_count / self.page_count

    @property
    def free_bytes(self) -> int:
        """Return the estimated bytes reclaimable by VACUUM."""
        return self.freelist_count * self.page_size


class DbBase:
    """Database base class: init, lifecycle, and shared helpers."""

    @staticmethod
    def _coerce_datetime(value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return ensure_utc(value)
        return parse_iso_datetime(value)

    @staticmethod
    def _to_core_session(row: db_models.Session) -> Session:
        origin_metadata: JsonDict = {}
        if hasattr(row, "origin_metadata") and row.origin_metadata:
            try:
                parsed: object = json.loads(row.origin_metadata)
                if isinstance(parsed, dict):
                    origin_metadata = to_json_dict(parsed)
            except json.JSONDecodeError:
                pass

        return Session(
            session_id=row.session_id,
            computer_name=row.computer_name,
            tmux_session_name=row.tmux_session_name,
            last_input_origin=row.last_input_origin,
            title=row.title or "",
            origin_metadata=origin_metadata,
            role=row.role if hasattr(row, "role") else None,
            job=row.job if hasattr(row, "job") else None,
            company=row.company if hasattr(row, "company") else None,
            created_at=DbBase._coerce_datetime(row.created_at),
            last_activity=DbBase._coerce_datetime(row.last_activity),
            runtime_start_observed=bool(getattr(row, "runtime_start_observed", False)),
            runtime_run_id=getattr(row, "runtime_run_id", None),
            runtime_turn_id=getattr(row, "runtime_turn_id", None),
            runtime_activity_at=DbBase._coerce_datetime(getattr(row, "runtime_activity_at", None)),
            agent_status=AgentStatusValue(row.agent_status),
            agent_status_reason=AgentStatusReason(row.agent_status_reason) if row.agent_status_reason else None,
            agent_status_since=DbBase._coerce_datetime(row.agent_status_since),
            open_tool_calls=decode_open_tool_calls(row.open_tool_calls, session_id=row.session_id),
            agent_status_version=row.agent_status_version,
            lifecycle_transitioned_at=DbBase._coerce_datetime(getattr(row, "lifecycle_transitioned_at", None)),
            lifecycle_transition_reason=getattr(row, "lifecycle_transition_reason", None),
            closed_at=DbBase._coerce_datetime(row.closed_at),
            deleted_at=DbBase._coerce_datetime(row.deleted_at),
            project_path=row.project_path,
            subdir=row.subdir,
            config_subject=row.config_subject,
            subject_owner=getattr(row, SessionField.SUBJECT_OWNER.value, None),
            description=row.description,
            initiated_by_ai=bool(row.initiated_by_ai) if row.initiated_by_ai is not None else False,
            initiator_session_id=row.initiator_session_id,
            initiator_computer=row.initiator_computer if hasattr(row, "initiator_computer") else None,
            detached=bool(row.detached) if hasattr(row, "detached") and row.detached is not None else False,
            output_message_id=row.output_message_id,
            turn_notifications_sent=decode_turn_notifications(row.turn_notifications_sent, session_id=row.session_id),
            native_session_id=row.native_session_id,
            native_log_file=row.native_log_file,
            active_agent=row.active_agent,
            thinking_mode=row.thinking_mode,
            tui_log_file=row.tui_log_file,
            tui_capture_started=bool(row.tui_capture_started) if row.tui_capture_started is not None else False,
            last_message_sent=row.last_message_sent,
            last_input=row.last_input,
            last_input_written_at=DbBase._coerce_datetime(getattr(row, "last_input_written_at", None)),
            last_message_sent_at=DbBase._coerce_datetime(row.last_message_sent_at),
            last_projected_at=DbBase._coerce_datetime(
                row.last_projected_at if hasattr(row, "last_projected_at") else None
            ),
            last_output_raw=row.last_output_raw,
            last_output_stop_at=DbBase._coerce_datetime(
                row.last_output_stop_at if hasattr(row, "last_output_stop_at") else None
            ),
            last_output_at=DbBase._coerce_datetime(row.last_output_at),
            last_tool_done_at=DbBase._coerce_datetime(row.last_tool_done_at),
            last_tool_use_at=DbBase._coerce_datetime(row.last_tool_use_at),
            last_checkpoint_at=DbBase._coerce_datetime(row.last_checkpoint_at),
            last_agent_stop_at=DbBase._coerce_datetime(row.last_agent_stop_at),
            last_agent_idle_at=DbBase._coerce_datetime(row.last_agent_idle_at),
            last_output_summary=row.last_output_summary,
            last_output_digest=row.last_output_digest,
            last_projected_output_digest=(
                row.last_projected_output_digest if hasattr(row, "last_projected_output_digest") else None
            ),
            command=row.command,
            working_slug=row.working_slug,
            human_email=row.human_email,
            human_role=row.human_role,
            principal=row.principal if hasattr(row, "principal") else None,
            lifecycle_status=row.lifecycle_status or "initializing",
            help_desk_processed_at=DbBase._coerce_datetime(row.help_desk_processed_at),
            idle_compaction_requested_at=DbBase._coerce_datetime(row.idle_compaction_requested_at),
            idle_compaction_completed_at=DbBase._coerce_datetime(row.idle_compaction_completed_at),
            idle_closed_at=DbBase._coerce_datetime(row.idle_closed_at),
            relay_status=row.relay_status,
            relay_channel_id=row.relay_channel_id,
            relay_started_at=DbBase._coerce_datetime(row.relay_started_at),
            relay_exchange=decode_relay_exchange(row.relay_exchange),
            transcript_files=row.transcript_files or "[]",
            char_offset=int(row.char_offset) if row.char_offset is not None else 0,
            visibility=row.visibility if hasattr(row, "visibility") else "private",
        )

    def __init__(self, db_path: str) -> None:
        """Initialize database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._engine: AsyncEngine | None = None
        self._sessionmaker: object | None = None
        self._outbox_engine: AsyncEngine | None = None
        self._outbox_sessionmaker: object | None = None
        self._store_engines: dict[DaemonStore, AsyncEngine] = {}
        self._store_sessionmakers: dict[DaemonStore, object] = {}
        self.conn: aiosqlite.Connection | None = None
        self._temp_db_path: str | None = None
        self._temp_dir: str | None = None

    async def initialize(self) -> None:
        """Initialize the core database and every split store: create tables and run migrations."""
        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        db_path = self.db_path
        if self.db_path == DB_IN_MEMORY:
            # Isolate the whole database set (main, stores, outbox, events) in a private
            # per-instance directory. A bare temp file would share its parent —
            # the system temp dir — so every in-memory Db would derive the same
            # sibling paths and leak rows across instances (and across tests).
            self._temp_dir = tempfile.mkdtemp(prefix="teleclaude-db-")
            self._temp_db_path = os.path.join(self._temp_dir, "main.db")
            db_path = self._temp_db_path
        home_dir = Path(db_path).expanduser().parent
        outbox_db_path = str(get_outbox_db_path(home_dir))
        guarded = self.db_path != DB_IN_MEMORY

        # The core database first: its pending migrations may move tables into a store's file, which the
        # store's own bootstrap then finds already populated.
        await self._bootstrap_database(db_path, CORE_SCHEMA_PATH, MIGRATIONS_DIR, MigrationStore.CORE_DATABASE, guarded)
        for store, declaration in STORES.items():
            await self._bootstrap_database(
                str(store_db_path(store, home_dir)),
                declaration.schema_file,
                declaration.migrations_dir,
                declaration.migration_store,
                guarded,
            )

        # Async engines for runtime access. A throwaway in-memory database (tests)
        # pins a single reused connection per file; on-disk databases use the SQLite
        # dialect's pooled default.
        self._engine = _create_runtime_engine(db_path, pooled=guarded)
        self._outbox_engine = _create_runtime_engine(outbox_db_path, pooled=guarded)
        self._sessionmaker = sessionmaker(self._engine, expire_on_commit=False, class_=SqlAsyncSession)
        self._outbox_sessionmaker = sessionmaker(self._outbox_engine, expire_on_commit=False, class_=SqlAsyncSession)
        for store in STORES:
            engine = _create_runtime_engine(store_db_path(store, home_dir), pooled=guarded)
            self._store_engines[store] = engine
            self._store_sessionmakers[store] = sessionmaker(engine, expire_on_commit=False, class_=SqlAsyncSession)

    async def _bootstrap_database(
        self,
        db_path: str,
        schema_path: Path,
        migrations_dir: Path,
        migration_store: MigrationStore,
        guarded: bool,
    ) -> None:
        """Bring one daemon database file to its current schema, its migration ledger kept inside it.

        ``guarded`` applies the todo-worktree rules: such a process neither creates the file from empty
        nor runs its pending migrations.
        """
        self.conn = await aiosqlite.connect(db_path)
        self.conn.row_factory = aiosqlite.Row

        # An empty database is about to be created from the current schema, so
        # its migration history is recorded rather than replayed over it.
        created_from_current_schema = not await self._has_user_tables(self.conn)

        if created_from_current_schema and guarded and _invoked_from_slug_worktree():
            # Refuse before writing any schema: creating this database's first
            # generation is a canonical-checkout or daemon-owned act. Baselining
            # it here would bake this worktree's own undelivered migrations into
            # the ledger as applied, which is only safe for a schema-shaped
            # migration and silently destroys a data-shaped one.
            await self.conn.close()
            self.conn = None
            raise WorktreeDatabaseBootstrapRefused(_WORKTREE_BOOTSTRAP_REFUSAL_TEMPLATE % db_path)

        schema_sql = schema_path.read_text(encoding="utf-8")

        if created_from_current_schema:
            await self.conn.executescript(schema_sql)  # guard: raw-sql
            await self.conn.commit()
            # Reached only for a genuine bootstrap not invoked from a worktree
            # (canonical checkout or daemon) — recording the current migration
            # set as applied is correct because this call owns the schema it
            # just wrote.
            await baseline_migrations(self.conn, migrations_dir)
        else:
            # Pending migrations run against the shape their predecessors left,
            # before the current schema adds anything: each one finds the input
            # it was written for, however many releases the database skipped.
            # The current schema then only adds what the history does not create.
            if guarded and _invoked_from_slug_worktree():
                logger.debug(_MIGRATION_WORKTREE_SKIP_MESSAGE, db_path)
            else:
                await run_pending_migrations(self.conn, migrations_dir, migration_store)
            await self.conn.executescript(schema_sql)  # guard: raw-sql
            await self.conn.commit()

        # Close bootstrap connection — runtime access uses the SQLAlchemy pool
        await self.conn.close()
        self.conn = None

    @staticmethod
    async def _has_user_tables(conn: aiosqlite.Connection) -> bool:
        """Return whether a bootstrap connection already holds application tables."""
        async with conn.execute(_USER_TABLE_COUNT_SQL) as cursor:  # guard: raw-sql
            row = await cursor.fetchone()
        return bool(row) and int(row[0]) > 0

    def _session(self) -> SqlAsyncSession:
        """Create an async ORM session from the initialized session factory."""
        if self._sessionmaker is None:
            raise RuntimeError(DB_NOT_INITIALIZED_ERROR)
        return self._sessionmaker()  # type: ignore[call-arg]

    def _outbox_session(self) -> SqlAsyncSession:
        """Create an async ORM session bound to the dedicated outbox database."""
        if self._outbox_sessionmaker is None:
            raise RuntimeError(DB_NOT_INITIALIZED_ERROR)
        return self._outbox_sessionmaker()  # type: ignore[call-arg]

    def _store_session(self, store: DaemonStore) -> SqlAsyncSession:
        """Create an async ORM session bound to one split store's database."""
        sessionmaker_for_store = self._store_sessionmakers.get(store)
        if sessionmaker_for_store is None:
            raise RuntimeError(DB_NOT_INITIALIZED_ERROR)
        return sessionmaker_for_store()  # type: ignore[operator]

    async def _retained_session_ids(self, *, closed_since: datetime | None = None) -> set[str]:
        """Return the ids of sessions that retention keeps.

        A session is retained while it is open; with ``closed_since``, also when it closed at or after that
        instant.
        """
        retained = and_(
            db_models.Session.closed_at.is_(None),
            or_(
                db_models.Session.lifecycle_status.is_(None),
                db_models.Session.lifecycle_status != "closed",
            ),
        )
        if closed_since is not None:
            retained = or_(retained, db_models.Session.closed_at >= closed_since)
        async with self._session() as db_session:
            result = await db_session.exec(select(db_models.Session.session_id).where(retained))
            return set(result.all())

    def is_initialized(self) -> bool:
        """Return whether the async session factory has been initialized."""
        return self._sessionmaker is not None

    def set_client(self, client: "AdapterClient") -> None:
        """Deprecated no-op: events are emitted via the global event bus."""
        _ = client

    async def wal_checkpoint(self) -> None:
        """Run WAL checkpoint to prevent unbounded WAL growth."""
        async with self._session() as session:
            result = await session.exec(text("PRAGMA wal_checkpoint(TRUNCATE)"))  # guard: raw-sql
            row = result.first()
            if row:
                logger.debug("WAL checkpoint: busy=%s, log=%s, checkpointed=%s", *row)

    @staticmethod
    async def get_sqlite_database_stats(path: str | Path) -> SqliteDatabaseStats:
        """Return page/freelist statistics for a SQLite database file."""
        async with aiosqlite.connect(str(Path(path).expanduser())) as conn:
            page_count = await DbBase._pragma_int(conn, "PRAGMA page_count")
            freelist_count = await DbBase._pragma_int(conn, "PRAGMA freelist_count")
            page_size = await DbBase._pragma_int(conn, "PRAGMA page_size")
        return SqliteDatabaseStats(page_count=page_count, freelist_count=freelist_count, page_size=page_size)

    @staticmethod
    async def _pragma_int(conn: aiosqlite.Connection, statement: str) -> int:
        cursor = await conn.execute(statement)  # guard: raw-sql
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def compact_sqlite_database_if_needed(
        self,
        path: str | Path,
        *,
        min_freelist_ratio: float = RUNTIME_COMPACTION_MIN_FREELIST_RATIO,
        min_free_bytes: int = RUNTIME_COMPACTION_MIN_FREE_BYTES,
    ) -> bool:
        """VACUUM a SQLite file only when retained freelist space crosses thresholds."""
        db_path = Path(path).expanduser()
        if not db_path.is_file():
            return False

        stats = await self.get_sqlite_database_stats(db_path)
        if stats.freelist_ratio < min_freelist_ratio or stats.free_bytes < min_free_bytes:
            return False

        try:
            await self._compact_sqlite_database(db_path)
        except aiosqlite.Error:
            logger.warning("SQLite runtime compaction skipped for %s", db_path, exc_info=True)
            return False
        return True

    @staticmethod
    async def _compact_sqlite_database(path: Path) -> None:
        async with aiosqlite.connect(str(path)) as conn:
            await conn.execute("PRAGMA busy_timeout = 5000")  # guard: raw-sql
            await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # guard: raw-sql
            await conn.commit()
            await conn.execute("VACUUM")  # guard: raw-sql
            await conn.commit()

    def _runtime_main_db_path(self) -> Path | None:
        target = self._temp_db_path if self._temp_db_path is not None else self.db_path
        if target == DB_IN_MEMORY or str(target).startswith("file:"):
            return None
        return Path(target).expanduser()

    async def compact_runtime_databases_if_needed(self) -> int:
        """Compact bounded runtime SQLite files while leaving history databases untouched."""
        main_path = self._runtime_main_db_path()
        if main_path is None:
            return 0

        runtime_paths = (
            main_path,
            get_outbox_db_path(main_path.parent),
            main_path.with_name(EVENTS_DB_PATH.name),
            *(store_db_path(store, main_path.parent) for store in STORES),
        )
        compacted = 0
        seen_paths: set[Path] = set()
        for runtime_path in runtime_paths:
            db_path = runtime_path.expanduser()
            if db_path in seen_paths:
                continue
            seen_paths.add(db_path)
            if await self.compact_sqlite_database_if_needed(db_path):
                compacted += 1
        return compacted

    async def close(self) -> None:
        """Close database connection."""
        if self._engine:
            await self._engine.dispose()
        if self._outbox_engine:
            await self._outbox_engine.dispose()
        for store_engine in self._store_engines.values():
            await store_engine.dispose()
        if self.conn:
            await self.conn.close()
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        elif self._temp_db_path:
            try:
                os.remove(self._temp_db_path)
            except OSError:
                pass
