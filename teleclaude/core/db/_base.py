"""Database base class: lifecycle, static helpers, and shared infrastructure."""

import dataclasses
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite
from instrukt_ai_logging import get_logger
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import DB_IN_MEMORY

from .. import db_models
from ..dates import ensure_utc, parse_iso_datetime
from ..models import Session, SessionAdapterMetadata, SessionMetadata

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

_SM_FIELDS = {"system_role", "job", "human_email", "human_role", "principal"}


class DbBase:
    """Database base class: init, lifecycle, and shared helpers."""

    @staticmethod
    def _serialize_adapter_metadata(
        value: SessionAdapterMetadata
        | dict[str, object]  # guard: loose-dict - Adapter metadata JSON payload.
        | str
        | None,
    ) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return json.dumps(value)
        return value.to_json()

    @staticmethod
    def _serialize_session_metadata(
        value: SessionMetadata | None,
    ) -> str | None:
        if value is None:
            return None
        return json.dumps(dataclasses.asdict(value))

    @staticmethod
    def _coerce_datetime(value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return ensure_utc(value)
        return parse_iso_datetime(value)

    @staticmethod
    def _to_core_session(row: db_models.Session) -> Session:
        adapter_metadata = (
            SessionAdapterMetadata.from_json(row.adapter_metadata)
            if isinstance(row.adapter_metadata, str) and row.adapter_metadata
            else SessionAdapterMetadata()
        )
        session_metadata: SessionMetadata | None = None
        if row.session_metadata:
            try:
                _raw = json.loads(row.session_metadata)
                if isinstance(_raw, dict):
                    session_metadata = SessionMetadata(**{k: v for k, v in _raw.items() if k in _SM_FIELDS})
            except json.JSONDecodeError:
                pass

        return Session(
            session_id=row.session_id,
            computer_name=row.computer_name,
            tmux_session_name=row.tmux_session_name,
            last_input_origin=row.last_input_origin,
            title=row.title or "",
            adapter_metadata=adapter_metadata,
            session_metadata=session_metadata,
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
        from teleclaude.core.migrations.runner import run_pending_migrations

        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        db_path = self.db_path
        use_uri = False
        if self.db_path == DB_IN_MEMORY:
            temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            self._temp_db_path = temp_file.name
            temp_file.close()
            db_path = self._temp_db_path

        # Ensure schema + migrations via aiosqlite (single-shot bootstrap)
        self.conn = await aiosqlite.connect(db_path, uri=use_uri)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode = WAL")  # noqa: raw-sql
        await self.conn.execute("PRAGMA synchronous = NORMAL")  # noqa: raw-sql
        await self.conn.execute("PRAGMA busy_timeout = 5000")  # noqa: raw-sql

        schema_path = Path(__file__).parent.parent / "schema.sql"
        with open(schema_path, encoding="utf-8") as f:
            schema_sql = f.read()

        await self.conn.executescript(schema_sql)  # noqa: raw-sql
        await self.conn.commit()

        await run_pending_migrations(self.conn)

        # Close bootstrap connection — runtime access uses the SQLAlchemy pool
        await self.conn.close()
        self.conn = None

        # Async engine for runtime access
        db_url = f"sqlite+aiosqlite:///{db_path}"
        from sqlalchemy import event  # noqa: raw-sql - PRAGMAs require raw SQL
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.orm import sessionmaker

        connect_args = {"uri": True} if use_uri else {}
        self._engine = create_async_engine(
            db_url,
            future=True,
            connect_args=connect_args,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
        )
        self._sessionmaker = sessionmaker(self._engine, expire_on_commit=False, class_=SqlAsyncSession)

        # Apply PRAGMAs to every new connection via pool event listener.
        # This ensures all pooled connections have WAL mode, busy timeout, etc.
        @event.listens_for(self._engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL")  # noqa: raw-sql
            cursor.execute("PRAGMA synchronous = NORMAL")  # noqa: raw-sql
            cursor.execute("PRAGMA busy_timeout = 5000")  # noqa: raw-sql
            cursor.execute("PRAGMA cache_size = -8000")  # noqa: raw-sql  8MB per connection
            cursor.close()

        await self._normalize_adapter_metadata()

    async def _normalize_adapter_metadata(self) -> None:
        """Normalize adapter_metadata types (e.g., topic_id stored as string)."""
        from sqlalchemy.exc import OperationalError

        async with self._session() as session:
            from sqlmodel import select

            try:
                result = await session.exec(select(db_models.Session))
            except OperationalError:
                return
            rows = result.all()
            if not rows:
                return

            any_updated = False
            for row in rows:
                raw = row.adapter_metadata
                if not isinstance(raw, str) or not raw:
                    continue
                try:
                    parsed: object = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(parsed, dict):
                    continue
                tg = parsed.get("telegram")
                row_updated = False
                if isinstance(tg, dict):
                    topic_id = tg.get("topic_id")
                    if isinstance(topic_id, str) and topic_id.isdigit():
                        tg["topic_id"] = int(topic_id)
                        row_updated = True
                if row_updated:
                    row.adapter_metadata = json.dumps(parsed)
                    session.add(row)
                    any_updated = True

            if any_updated:
                await session.commit()

    def _session(self) -> SqlAsyncSession:
        if self._sessionmaker is None:
            raise RuntimeError("Database not initialized - call initialize() first")
        return self._sessionmaker()  # type: ignore[call-arg]

    def is_initialized(self) -> bool:
        return self._sessionmaker is not None

    def set_client(self, client: "AdapterClient") -> None:
        """Deprecated no-op: events are emitted via the global event bus."""
        _ = client

    async def wal_checkpoint(self) -> None:
        """Run WAL checkpoint to prevent unbounded WAL growth."""
        async with self._session() as session:
            from sqlalchemy import text  # noqa: raw-sql - PRAGMA requires raw SQL

            result = await session.exec(text("PRAGMA wal_checkpoint(TRUNCATE)"))  # noqa: raw-sql
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
