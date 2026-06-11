"""Database base class: lifecycle, static helpers, and shared infrastructure."""

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite
from instrukt_ai_logging import get_logger
from sqlalchemy import text  # guard: raw-sql
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import DB_IN_MEMORY
from teleclaude.core.migrations.runner import run_pending_migrations
from teleclaude.paths import EVENTS_DB_PATH

from .. import db_models
from ..dates import ensure_utc, parse_iso_datetime
from ..models import Session
from .connection_factory import create_async_db_engine, get_outbox_db_path

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

RUNTIME_COMPACTION_MIN_FREELIST_RATIO = 0.20
RUNTIME_COMPACTION_MIN_FREE_BYTES = 16 * 1024 * 1024


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
        origin_metadata: dict[str, object] = {}  # guard: loose-dict - JSON blob from DB
        if hasattr(row, "origin_metadata") and row.origin_metadata:
            try:
                parsed = json.loads(row.origin_metadata)
                if isinstance(parsed, dict):
                    origin_metadata = parsed
            except json.JSONDecodeError:
                pass

        return Session(
            session_id=row.session_id,
            computer_name=row.computer_name,
            tmux_session_name=row.tmux_session_name,
            last_input_origin=row.last_input_origin,
            title=row.title or "",
            origin_metadata=origin_metadata,
            system_role=row.system_role if hasattr(row, "system_role") else None,
            job=row.job if hasattr(row, "job") else None,
            created_at=DbBase._coerce_datetime(row.created_at),
            last_activity=DbBase._coerce_datetime(row.last_activity),
            closed_at=DbBase._coerce_datetime(row.closed_at),
            project_path=row.project_path,
            subdir=row.subdir,
            description=row.description,
            initiated_by_ai=bool(row.initiated_by_ai) if row.initiated_by_ai is not None else False,
            initiator_session_id=row.initiator_session_id,
            detached=bool(row.detached) if hasattr(row, "detached") and row.detached is not None else False,
            output_message_id=row.output_message_id,
            notification_sent=bool(row.notification_sent) if row.notification_sent is not None else False,
            native_session_id=row.native_session_id,
            native_log_file=row.native_log_file,
            active_agent=row.active_agent,
            thinking_mode=row.thinking_mode,
            tui_log_file=row.tui_log_file,
            tui_capture_started=bool(row.tui_capture_started) if row.tui_capture_started is not None else False,
            last_message_sent=row.last_message_sent,
            last_message_sent_at=DbBase._coerce_datetime(row.last_message_sent_at),
            last_projected_at=DbBase._coerce_datetime(
                row.last_projected_at if hasattr(row, "last_projected_at") else None
            ),
            last_output_raw=row.last_output_raw,
            last_output_at=DbBase._coerce_datetime(row.last_output_at),
            last_tool_done_at=DbBase._coerce_datetime(row.last_tool_done_at),
            last_tool_use_at=DbBase._coerce_datetime(row.last_tool_use_at),
            last_checkpoint_at=DbBase._coerce_datetime(row.last_checkpoint_at),
            last_agent_stop_at=DbBase._coerce_datetime(row.last_agent_stop_at),
            last_output_summary=row.last_output_summary,
            last_output_digest=row.last_output_digest,
            last_projected_output_digest=(
                row.last_projected_output_digest if hasattr(row, "last_projected_output_digest") else None
            ),
            working_slug=row.working_slug,
            human_email=row.human_email,
            human_role=row.human_role,
            principal=row.principal if hasattr(row, "principal") else None,
            lifecycle_status=row.lifecycle_status or "active",
            last_memory_extraction_at=DbBase._coerce_datetime(row.last_memory_extraction_at),
            help_desk_processed_at=DbBase._coerce_datetime(row.help_desk_processed_at),
            relay_status=row.relay_status,
            relay_discord_channel_id=row.relay_discord_channel_id,
            relay_started_at=DbBase._coerce_datetime(row.relay_started_at),
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
        self.conn: aiosqlite.Connection | None = None
        self._temp_db_path: str | None = None

    async def initialize(self) -> None:
        """Initialize database, create tables, and run migrations."""
        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        db_path = self.db_path
        use_uri = False
        if self.db_path == DB_IN_MEMORY:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
                self._temp_db_path = temp_file.name
            db_path = self._temp_db_path
        outbox_db_path = str(get_outbox_db_path(Path(db_path).expanduser().parent))

        # Ensure schema + migrations via aiosqlite (single-shot bootstrap)
        self.conn = await aiosqlite.connect(db_path, uri=use_uri)
        self.conn.row_factory = aiosqlite.Row

        schema_path = Path(__file__).parent.parent / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")

        await self.conn.executescript(schema_sql)  # guard: raw-sql
        await self.conn.commit()

        await run_pending_migrations(self.conn)

        # Close bootstrap connection — runtime access uses the SQLAlchemy pool
        await self.conn.close()
        self.conn = None

        # Async engine for runtime access
        self._engine = create_async_db_engine(db_path)
        self._sessionmaker = sessionmaker(self._engine, expire_on_commit=False, class_=SqlAsyncSession)
        self._outbox_engine = create_async_db_engine(outbox_db_path)
        self._outbox_sessionmaker = sessionmaker(self._outbox_engine, expire_on_commit=False, class_=SqlAsyncSession)

    def _session(self) -> SqlAsyncSession:
        """Create an async ORM session from the initialized session factory."""
        if self._sessionmaker is None:
            raise RuntimeError("Database not initialized - call initialize() first")
        return self._sessionmaker()  # type: ignore[call-arg]

    def _outbox_session(self) -> SqlAsyncSession:
        """Create an async ORM session bound to the dedicated outbox database."""
        if self._outbox_sessionmaker is None:
            raise RuntimeError("Database not initialized - call initialize() first")
        return self._outbox_sessionmaker()  # type: ignore[call-arg]

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
        if self.conn:
            await self.conn.close()
        if self._temp_db_path:
            try:
                os.remove(self._temp_db_path)
            except OSError:
                pass
