"""Explicit live terminal observation for agent-runtime session reads."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from teleclaude.core.db import db
from teleclaude.core.models import Session
from teleclaude.core.tmux_bridge import PaneSnapshot, collect_pane_snapshot
from teleclaude.utils import strip_ansi_codes


class SessionPaneDb(Protocol):
    """Storage capability required by the pane observation query."""

    async def get_session(self, session_id: str) -> Session | None: ...


PaneSnapshotCollector = Callable[[str], Awaitable[PaneSnapshot]]


@dataclass(frozen=True)
class SessionPaneResult:
    """One independent observation of a session's live terminal."""

    session_id: str
    runtime: str | None
    captured_at: datetime
    available: bool
    text: str


async def get_session_pane(
    session_id: str,
    *,
    database: SessionPaneDb = db,
    collect_snapshot: PaneSnapshotCollector = collect_pane_snapshot,
) -> SessionPaneResult:
    """Capture the current terminal pane without reading conversation state."""
    session = await database.get_session(session_id)
    if session is None:
        raise LookupError(session_id)
    captured_at = datetime.now(UTC)
    if not session.tmux_session_name:
        return SessionPaneResult(session_id, session.active_agent, captured_at, False, "")
    snapshot = await collect_snapshot(session.tmux_session_name)
    if not snapshot.session_exists:
        return SessionPaneResult(session_id, session.active_agent, captured_at, False, "")
    return SessionPaneResult(
        session_id,
        session.active_agent,
        captured_at,
        True,
        strip_ansi_codes(snapshot.output_raw),
    )
