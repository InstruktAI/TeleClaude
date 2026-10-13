"""Synchronous main-database reads shared by hook processes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import sqlmodel
from instrukt_ai_logging import get_logger
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import load_only
from sqlalchemy.orm.attributes import QueryableAttribute
from sqlmodel import Session as SqlSession

from teleclaude import paths as tc_paths
from teleclaude.core import db_models
from teleclaude.core.db.connection_factory import create_sync_db_engine
from teleclaude.core.next_machine.lanes import LifecycleProcedure
from teleclaude.core.next_machine.runtime.sessions import is_commit_reviewer_in_project
from teleclaude.core.session_status import is_session_terminal

logger = get_logger(__name__)

__all__ = ["live_commit_reviewer_ids", "main_sync_engine"]

_sync_engine: Engine | None = None


def main_sync_engine() -> Engine:
    """Return the process-wide sync engine for the main database."""
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_sync_db_engine(tc_paths.MAIN_DB_PATH)
    return _sync_engine


def live_commit_reviewer_ids(initiator_session_id: str, project_path: str) -> frozenset[str]:
    """Return the live commit-review sessions this session started in ``project_path``."""
    columns = tuple(
        cast(QueryableAttribute[Any], column)
        for column in (
            db_models.Session.session_id,
            db_models.Session.command,
            db_models.Session.project_path,
            db_models.Session.closed_at,
            db_models.Session.lifecycle_status,
        )
    )
    project_root = Path(project_path).resolve()
    try:
        with SqlSession(main_sync_engine()) as session:
            rows = session.exec(
                sqlmodel.select(db_models.Session)
                .where(db_models.Session.initiator_session_id == initiator_session_id)
                .options(load_only(*columns, raiseload=True))
            ).all()
    except SQLAlchemyError as exc:
        # The checkpoint fails open: without the lookup, only a fresh review run counts.
        logger.warning("live_commit_reviewer_lookup_failed", session_id=initiator_session_id, error=str(exc))
        return frozenset()
    return frozenset(
        row.session_id
        for row in rows
        if not is_session_terminal(lifecycle_status=row.lifecycle_status, closed_at=row.closed_at)
        and is_commit_reviewer_in_project(
            command=row.command,
            session_project_path=row.project_path,
            project_root=project_root,
            command_value=LifecycleProcedure.REVIEW_COMMITS.value,
        )
    )
