"""Memory search for finding observations via FTS5 or LIKE fallback."""

from __future__ import annotations

import json
from typing import Any

from instrukt_ai_logging import get_logger
from sqlalchemy import create_engine, text  # noqa: raw-sql - Sync memory access
from sqlmodel import Session as SqlSession

from teleclaude.core.db import db
from teleclaude.memory.types import ObservationType, SearchResult

logger = get_logger(__name__)


def _row_to_search_result(row: Any) -> SearchResult:
    """Convert a raw SQL row to SearchResult."""
    if hasattr(row, "_mapping"):
        m = row._mapping
        facts_raw = m.get("facts")
    elif isinstance(row, tuple):
        # Tuple index layout: id, title, subtitle, type, project, narrative, facts, created_at, created_at_epoch
        facts_raw = row[6]
        return SearchResult(
            id=row[0],
            title=row[1],
            subtitle=row[2],
            type=row[3],
            project=row[4],
            narrative=row[5],
            facts=json.loads(facts_raw) if facts_raw else [],
            created_at=row[7],
            created_at_epoch=row[8],
        )
    else:
        m = {}

    facts_raw = m.get("facts") if isinstance(m, dict) else getattr(row, "facts", None)
    return SearchResult(
        id=m.get("id") or getattr(row, "id", 0),
        title=m.get("title") or getattr(row, "title", None),
        subtitle=m.get("subtitle") or getattr(row, "subtitle", None),
        type=m.get("type") or getattr(row, "type", ""),
        project=m.get("project") or getattr(row, "project", ""),
        narrative=m.get("narrative") or getattr(row, "narrative", None),
        facts=json.loads(facts_raw) if facts_raw else [],
        created_at=m.get("created_at") or getattr(row, "created_at", ""),
        created_at_epoch=m.get("created_at_epoch") or getattr(row, "created_at_epoch", 0),
    )


_SEARCH_COLUMNS = "id, title, subtitle, type, project, narrative, facts, created_at, created_at_epoch"


class MemorySearch:
    """Search memory observations via FTS5 or LIKE fallback."""

    async def search(
        self,
        query: str,
        project: str | None = None,
        limit: int = 20,
        obs_type: ObservationType | None = None,
        identity_key: str | None = None,
    ) -> list[SearchResult]:
        """Search observations using FTS5 with LIKE fallback.

        Args:
            query: Search text.
            project: Filter by project.
            limit: Max results.
            obs_type: Filter by observation type for progressive disclosure.
            identity_key: Filter by identity scope (includes unscoped memories).
        """
        type_value = obs_type.value if obs_type else None

        async with db._session() as session:
            # Try FTS5 first
            try:
                sql = (
                    f"SELECT {_SEARCH_COLUMNS} FROM memory_observations "  # noqa: raw-sql
                    "WHERE id IN (SELECT rowid FROM memory_observations_fts WHERE memory_observations_fts MATCH :query)"
                )
                params: dict[str, str | int] = {"query": query, "limit": limit}
                if project:
                    sql += " AND project = :project"
                    params["project"] = project
                if type_value:
                    sql += " AND type = :obs_type"
                    params["obs_type"] = type_value
                if identity_key:
                    sql += " AND (identity_key IS NULL OR identity_key = :identity_key)"
                    params["identity_key"] = identity_key
                sql += " ORDER BY created_at_epoch DESC LIMIT :limit"
                result = await session.exec(text(sql).bindparams(**params))  # noqa: raw-sql
                rows = result.fetchall()
                return [_row_to_search_result(row) for row in rows]
            except Exception:
                logger.debug("FTS5 search failed, falling back to LIKE", query=query)

            # LIKE fallback
            like_pattern = f"%{query}%"
            sql = (
                f"SELECT {_SEARCH_COLUMNS} FROM memory_observations "  # noqa: raw-sql
                "WHERE (title LIKE :pattern OR narrative LIKE :pattern OR facts LIKE :pattern)"
            )
            params = {"pattern": like_pattern, "limit": limit}
            if project:
                sql += " AND project = :project"
                params["project"] = project
            if type_value:
                sql += " AND type = :obs_type"
                params["obs_type"] = type_value
            if identity_key:
                sql += " AND (identity_key IS NULL OR identity_key = :identity_key)"
                params["identity_key"] = identity_key
            sql += " ORDER BY created_at_epoch DESC LIMIT :limit"
            result = await session.exec(text(sql).bindparams(**params))  # noqa: raw-sql
            rows = result.fetchall()
            return [_row_to_search_result(row) for row in rows]

    async def timeline(
        self,
        anchor_id: int,
        depth_before: int = 3,
        depth_after: int = 3,
        project: str | None = None,
    ) -> list[SearchResult]:
        """Get observations around an anchor by created_at_epoch."""
        async with db._session() as session:
            # Get anchor epoch
            result = await session.exec(
                text(  # noqa: raw-sql
                    "SELECT created_at_epoch FROM memory_observations WHERE id = :id"
                ).bindparams(id=anchor_id)
            )
            anchor_row = result.first()
            if not anchor_row:
                return []
            anchor_epoch = anchor_row[0] if isinstance(anchor_row, tuple) else anchor_row.created_at_epoch

            # Before anchor
            before_sql = (
                f"SELECT {_SEARCH_COLUMNS} FROM memory_observations "  # noqa: raw-sql
                "WHERE created_at_epoch <= :epoch AND id != :id"
            )
            params_before: dict[str, str | int] = {"epoch": anchor_epoch, "id": anchor_id, "limit": depth_before}
            if project:
                before_sql += " AND project = :project"
                params_before["project"] = project
            before_sql += " ORDER BY created_at_epoch DESC LIMIT :limit"
            result = await session.exec(text(before_sql).bindparams(**params_before))  # noqa: raw-sql
            before_rows = list(reversed(result.fetchall()))

            # Anchor itself
            anchor_sql = f"SELECT {_SEARCH_COLUMNS} FROM memory_observations WHERE id = :id"  # noqa: raw-sql
            result = await session.exec(text(anchor_sql).bindparams(id=anchor_id))  # noqa: raw-sql
            anchor_rows = result.fetchall()

            # After anchor
            after_sql = (
                f"SELECT {_SEARCH_COLUMNS} FROM memory_observations "  # noqa: raw-sql
                "WHERE created_at_epoch >= :epoch AND id != :id"
            )
            params_after: dict[str, str | int] = {"epoch": anchor_epoch, "id": anchor_id, "limit": depth_after}
            if project:
                after_sql += " AND project = :project"
                params_after["project"] = project
            after_sql += " ORDER BY created_at_epoch ASC LIMIT :limit"
            result = await session.exec(text(after_sql).bindparams(**params_after))  # noqa: raw-sql
            after_rows = result.fetchall()

            all_rows = before_rows + list(anchor_rows) + list(after_rows)
            return [_row_to_search_result(row) for row in all_rows]

    async def batch_fetch(
        self,
        ids: list[int],
        project: str | None = None,
    ) -> list[SearchResult]:
        """Bulk fetch observations by IDs."""
        if not ids:
            return []
        placeholders = ", ".join([":id_" + str(i) for i in range(len(ids))])
        params: dict[str, str | int] = {f"id_{i}": id_val for i, id_val in enumerate(ids)}
        sql = f"SELECT {_SEARCH_COLUMNS} FROM memory_observations WHERE id IN ({placeholders})"  # noqa: raw-sql
        if project:
            sql += " AND project = :project"
            params["project"] = project
        sql += " ORDER BY created_at_epoch DESC"

        async with db._session() as session:
            result = await session.exec(text(sql).bindparams(**params))  # noqa: raw-sql
            rows = result.fetchall()
            return [_row_to_search_result(row) for row in rows]

    def search_sync(
        self,
        query: str,
        project: str | None = None,
        limit: int = 20,
        db_path: str = "",
    ) -> list[SearchResult]:
        """Sync search for hook receiver context generation."""
        engine = create_engine(f"sqlite:///{db_path}")
        with SqlSession(engine) as session:
            session.exec(text("PRAGMA journal_mode = WAL"))  # noqa: raw-sql
            session.exec(text("PRAGMA busy_timeout = 5000"))  # noqa: raw-sql

            # Try FTS5 first
            try:
                sql = (
                    f"SELECT {_SEARCH_COLUMNS} FROM memory_observations "  # noqa: raw-sql
                    "WHERE id IN (SELECT rowid FROM memory_observations_fts WHERE memory_observations_fts MATCH :query)"
                )
                params: dict[str, str | int] = {"query": query, "limit": limit}
                if project:
                    sql += " AND project = :project"
                    params["project"] = project
                sql += " ORDER BY created_at_epoch DESC LIMIT :limit"
                result = session.exec(text(sql).bindparams(**params))  # noqa: raw-sql
                rows = result.fetchall()
                return [_row_to_search_result(row) for row in rows]
            except Exception:
                pass

            # LIKE fallback
            like_pattern = f"%{query}%"
            sql = (
                f"SELECT {_SEARCH_COLUMNS} FROM memory_observations "  # noqa: raw-sql
                "WHERE (title LIKE :pattern OR narrative LIKE :pattern OR facts LIKE :pattern)"
            )
            params = {"pattern": like_pattern, "limit": limit}
            if project:
                sql += " AND project = :project"
                params["project"] = project
            sql += " ORDER BY created_at_epoch DESC LIMIT :limit"
            result = session.exec(text(sql).bindparams(**params))  # noqa: raw-sql
            rows = result.fetchall()
            return [_row_to_search_result(row) for row in rows]
