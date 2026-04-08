"""Shared SQLAlchemy engine factory for all TeleClaude SQLite databases."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

from teleclaude.constants import DB_IN_MEMORY
from teleclaude.core import db_models

_DEFAULT_OUTBOX_DB_NAME = "hook_outbox.db"
_POOL_SIZE_OVERRIDE_KEYS = {"pool_size", "max_overflow", "pool_timeout", "pool_recycle"}
_PRAGMA_STATEMENTS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA foreign_keys = ON",
    "PRAGMA cache_size = -8000",
)


def _is_outbox_db_path(db_path: str | Path) -> bool:
    """Return whether a target path is the dedicated hook outbox database."""
    target = str(db_path)
    if target == DB_IN_MEMORY or target.startswith("file:"):
        return False
    return Path(target).expanduser().name == _DEFAULT_OUTBOX_DB_NAME


def _normalize_sqlite_target(db_path: str | Path) -> tuple[str, bool]:
    """Return the SQLite URL target and whether it must be opened as a URI."""
    target = str(db_path)
    if target == DB_IN_MEMORY:
        return target, False
    if target.startswith("file:"):
        return target, True

    resolved = Path(db_path).expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return str(resolved), False


# guard: loose-dict-func - SQLAlchemy engine kwargs are intentionally open-ended.
def _build_engine_kwargs(overrides: dict[str, object], *, use_uri: bool) -> dict[str, object]:
    """Apply shared defaults while allowing explicit pool overrides."""
    engine_kwargs: dict[str, object] = {"future": True}
    engine_kwargs.update(overrides)

    connect_args_raw = engine_kwargs.pop("connect_args", {})
    if not isinstance(connect_args_raw, dict):
        raise TypeError("connect_args override must be a dict")
    connect_args: dict[str, object] = {}
    for key, value in connect_args_raw.items():
        if not isinstance(key, str):
            raise TypeError("connect_args keys must be strings")
        connect_args[key] = value
    if use_uri:
        connect_args.setdefault("uri", True)
    if connect_args:
        engine_kwargs["connect_args"] = connect_args

    has_pool_override = "poolclass" in engine_kwargs or any(key in engine_kwargs for key in _POOL_SIZE_OVERRIDE_KEYS)
    if not has_pool_override:
        engine_kwargs["poolclass"] = NullPool

    return engine_kwargs


def _attach_pragma_listener(engine: Engine) -> None:
    """Attach the shared PRAGMA baseline to every new SQLite connection."""

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: sqlite3.Connection, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        try:
            for statement in _PRAGMA_STATEMENTS:
                try:
                    cursor.execute(statement)
                except sqlite3.OperationalError as exc:
                    # Read-only SQLite URIs cannot rewrite journal_mode, but the other
                    # connection-local pragmas remain safe and useful.
                    if "readonly" in str(exc).lower() and "journal_mode" in statement.lower():
                        continue
                    raise
        finally:
            cursor.close()


def create_async_db_engine(db_path: str | Path, **overrides: object) -> AsyncEngine:
    """Create an async SQLite engine with the shared PRAGMA baseline."""
    target, use_uri = _normalize_sqlite_target(db_path)
    if _is_outbox_db_path(db_path):
        bootstrap_engine = create_sync_db_engine(db_path)
        bootstrap_engine.dispose()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{target}",
        **_build_engine_kwargs(overrides, use_uri=use_uri),
    )
    _attach_pragma_listener(engine.sync_engine)
    return engine


def create_sync_db_engine(db_path: str | Path, **overrides: object) -> Engine:
    """Create a sync SQLite engine with the shared PRAGMA baseline."""
    target, use_uri = _normalize_sqlite_target(db_path)
    engine = create_engine(
        f"sqlite:///{target}",
        **_build_engine_kwargs(overrides, use_uri=use_uri),
    )
    _attach_pragma_listener(engine)
    if _is_outbox_db_path(db_path):
        init_outbox_schema(engine)
    return engine


def get_outbox_db_path(base_dir: str | Path) -> Path:
    """Return the canonical hook outbox database path within a TeleClaude home dir."""
    return Path(base_dir).expanduser() / _DEFAULT_OUTBOX_DB_NAME


def init_outbox_schema(engine: Engine) -> None:
    """Create the dedicated outbox table in the target database if it does not exist."""
    SQLModel.metadata.create_all(engine, tables=[db_models.HookOutbox.__table__])


__all__ = [
    "create_async_db_engine",
    "create_sync_db_engine",
    "get_outbox_db_path",
    "init_outbox_schema",
]
