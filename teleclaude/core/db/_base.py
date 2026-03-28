"""Database base class: lifecycle, static helpers, and shared infrastructure."""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite
from instrukt_ai_logging import get_logger
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import DB_IN_MEMORY
from teleclaude.core.migrations.runner import run_pending_migrations

from .. import db_models
from ..dates import ensure_utc, parse_iso_datetime
from ..models import Session

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


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
            last_output_raw=row.last_output_raw,
            last_output_at=DbBase._coerce_datetime(row.last_output_at),
            last_tool_done_at=DbBase._coerce_datetime(row.last_tool_done_at),
            last_tool_use_at=DbBase._coerce_datetime(row.last_tool_use_at),
            last_checkpoint_at=DbBase._coerce_datetime(row.last_checkpoint_at),
            last_agent_stop_at=DbBase._coerce_datetime(row.last_agent_stop_at),
            turn_triggered_by_linked_output=bool(row.turn_triggered_by_linked_output)
            if hasattr(row, "turn_triggered_by_linked_output")
            else False,
            last_output_summary=row.last_output_summary,
            last_output_digest=row.last_output_digest,
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

        # Ensure schema + migrations via aiosqlite (single-shot bootstrap)
        self.conn = await aiosqlite.connect(db_path, uri=use_uri)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode = WAL")  # guard: raw-sql
        await self.conn.execute("PRAGMA synchronous = NORMAL")  # guard: raw-sql
        await self.conn.execute("PRAGMA busy_timeout = 5000")  # guard: raw-sql

        schema_path = Path(__file__).parent.parent / "schema.sql"
        with open(schema_path, encoding="utf-8") as f:
            schema_sql = f.read()

        await self.conn.executescript(schema_sql)  # guard: raw-sql
        await self.conn.commit()

        await run_pending_migrations(self.conn)

        # Close bootstrap connection — runtime access uses the SQLAlchemy pool
        await self.conn.close()
        self.conn = None

        # Async engine for runtime access
        db_url = f"sqlite+aiosqlite:///{db_path}"

        connect_args = {"uri": True} if use_uri else {}
        self._engine = create_async_engine(
            db_url,
            future=True,
            connect_args=connect_args,
            poolclass=NullPool,
        )
        self._sessionmaker = sessionmaker(self._engine, expire_on_commit=False, class_=SqlAsyncSession)

        # Apply PRAGMAs to every new connection via pool event listener.
        # This ensures all pooled connections have WAL mode, busy timeout, etc.
        @event.listens_for(self._engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL")  # guard: raw-sql
            cursor.execute("PRAGMA synchronous = NORMAL")  # guard: raw-sql
            cursor.execute("PRAGMA busy_timeout = 5000")  # guard: raw-sql
            cursor.execute("PRAGMA cache_size = -8000")  # guard: raw-sql  8MB per connection
            cursor.close()

    def _session(self) -> SqlAsyncSession:
        """Create an async ORM session from the initialized session factory."""
        if self._sessionmaker is None:
            raise RuntimeError("Database not initialized - call initialize() first")
        return self._sessionmaker()  # type: ignore[call-arg]

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

    async def close(self) -> None:
        """Close database connection."""
        if self._engine:
            await self._engine.dispose()
        if self.conn:
            await self.conn.close()
        if self._temp_db_path:
            try:
                os.remove(self._temp_db_path)
            except OSError:
                pass
