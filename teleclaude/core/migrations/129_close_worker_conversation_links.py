"""Close every active conversation link that holds two worker sessions.

A worker reaches no other session, so no link holds two workers
(``local/projects/teleclaude/spec/feature/agent_runtime/direct-conversation-links``). A link closes the way
``sever_conversation_link`` closes it: status ``closed``, ``closed_at`` and ``updated_at`` set, member rows
removed. Each member's recorded role is read from ``sessions`` and classified by the role catalog; links with
fewer than two worker members are untouched.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Final

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.core.roles import is_focused_role

logger = get_logger(__name__)

_MIN_WORKER_MEMBERS: Final = 2
_SELECT_ACTIVE_MEMBER_ROLES_SQL: Final = (
    "SELECT m.link_id, s.role FROM conversation_link_members m "
    "JOIN conversation_links l ON l.link_id = m.link_id "
    "JOIN sessions s ON s.session_id = m.session_id "
    "WHERE l.status = 'active'"
)
_CLOSE_LINK_SQL: Final = (
    "UPDATE conversation_links SET status = 'closed', updated_at = ?, closed_at = ? WHERE link_id = ?"
)
_DELETE_MEMBERS_SQL: Final = "DELETE FROM conversation_link_members WHERE link_id = ?"
_CLOSED_EVENT: Final = "worker_conversation_links_closed"


async def up(db: aiosqlite.Connection) -> None:
    """End every active link whose members include two or more worker-class sessions."""
    cursor = await db.execute(_SELECT_ACTIVE_MEMBER_ROLES_SQL)
    rows = await cursor.fetchall()
    worker_members: defaultdict[str, int] = defaultdict(int)
    for link_id, role in rows:
        if is_focused_role(role):
            worker_members[link_id] += 1
    joined_workers = [link_id for link_id, count in worker_members.items() if count >= _MIN_WORKER_MEMBERS]
    now = datetime.now(UTC).isoformat()
    for link_id in joined_workers:
        await db.execute(_CLOSE_LINK_SQL, (now, now, link_id))
        await db.execute(_DELETE_MEMBERS_SQL, (link_id,))
    await db.commit()
    logger.info(_CLOSED_EVENT, closed_count=len(joined_workers))
