"""The builder's findings, supplied from the hook boundaries of its turns.

The receiver asks at a turn start and at a stop; a session that is not a builder inside a claiming group
of an item with unanswered findings gets nothing. The supply fails open: an unreadable item or database
never blocks a turn or a stop.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final, cast

from instrukt_ai_logging import get_logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.attributes import QueryableAttribute
from sqlmodel import Session as SqlSession

from teleclaude.core import db_models
from teleclaude.core.roles import RoleName
from teleclaude.core.workflow_machine.findings import (
    FindingsSupply,
    SupplyBoundary,
    read_findings,
    record_offered,
    render_supply,
)
from teleclaude.hooks.main_db import main_sync_engine
from teleclaude.hooks.session_map import (
    _load_projected_session_row,
)

logger = get_logger(__name__)

SUPPLY_FAILED_LOG: Final = "findings supply failed open"
OFFER_FAILED_LOG: Final = "findings offer could not be recorded"
GROUP_DEPTH_LIMIT: Final = 16


def _in_group(session_id: str, holder: str) -> bool:
    """Whether the session is the holder or descends from it through the sessions that started it."""
    current = session_id
    with SqlSession(main_sync_engine()) as db_session:
        for _ in range(GROUP_DEPTH_LIMIT):
            if current == holder:
                return True
            row = db_session.get(db_models.Session, current)
            initiator = row.initiator_session_id if row is not None else None
            if not initiator:
                return False
            current = initiator
    return False


async def _select(session_id: str, boundary: SupplyBoundary) -> FindingsSupply | None:
    row = _load_projected_session_row(
        session_id,
        *(
            cast(QueryableAttribute[Any], column)
            for column in (
                db_models.Session.role,
                db_models.Session.working_slug,
                db_models.Session.project_path,
                db_models.Session.initiator_session_id,
            )
        ),
    )
    if row is None or row.role != RoleName.BUILDER.value or not row.working_slug or not row.project_path:
        return None
    findings = await read_findings(row.project_path, row.working_slug, session_id, boundary)
    if findings is None or not findings.entries or not findings.holder:
        return None
    if not _in_group(session_id, findings.holder):
        return None
    return FindingsSupply(
        project_root=row.project_path,
        item=row.working_slug,
        session_id=session_id,
        text=render_supply(row.working_slug, findings.entries),
        keys=tuple(entry.key for entry in findings.entries),
    )


def findings_for_boundary(session_id: str, boundary: SupplyBoundary) -> FindingsSupply | None:
    """The findings this boundary owes the session, or nothing when it owes none or they cannot be read."""
    try:
        return asyncio.run(_select(session_id, boundary))
    except (SQLAlchemyError, OSError, ValueError, RuntimeError):
        logger.warning(SUPPLY_FAILED_LOG, session_id=session_id, boundary=boundary.value, exc_info=True)
        return None


def record_offer(supply: FindingsSupply) -> None:
    """Record a stop offer after its response was written; a failure only means the next stop offers again."""
    try:
        asyncio.run(record_offered(supply))
    except (SQLAlchemyError, OSError, ValueError, RuntimeError):
        logger.warning(OFFER_FAILED_LOG, session_id=supply.session_id, exc_info=True)
