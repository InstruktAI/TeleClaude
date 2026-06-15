"""Workflow state mutations driven by session lifecycle controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.db import Db
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.todos_db import get_todos_db
from teleclaude.events.envelope import EventLevel
from teleclaude.events.producer import emit_event
from teleclaude.types.todos import HoldAuditState

logger = get_logger(__name__)


@dataclass(frozen=True)
class ActiveRunnerMutationResult:
    slug: str | None
    project_path: str | None
    mutated: bool
    reason: str


async def _emit_todo_updated(*, slug: str, project_path: str, source: str) -> None:
    try:
        await emit_event(
            event="workflow.todo.updated",
            source=source,
            level=EventLevel.WORKFLOW,
            domain="software-development",
            payload={
                "slug": slug,
                "project_path": project_path,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
    except RuntimeError:
        logger.info("workflow.todo.updated not emitted: event producer unavailable", slug=slug)


async def _emit_session_ended(*, session_id: str, project_path: str) -> None:
    try:
        await emit_event(
            event="agent_runtime.session.ended",
            source="agent_runtime",
            level=EventLevel.WORKFLOW,
            domain="agent_runtime",
            payload={
                "session_id": session_id,
                "project_path": project_path,
                "ended_at": datetime.now(UTC).isoformat(),
            },
        )
    except RuntimeError:
        logger.info("agent_runtime.session.ended not emitted: event producer unavailable", session_id=session_id)


async def _active_runner_slug(db: Db, session_id: str) -> tuple[str | None, str | None, str]:
    session = await db.get_session(session_id)
    if session is None:
        return None, None, "session-not-found"
    if not session.project_path:
        return None, None, "session-project-missing"
    project_path = str(Path(session.project_path).resolve())
    todos_db = await get_todos_db(project_path)
    matches: list[str] = []
    for row in await todos_db.list_roadmap(include_icebox=True):
        state = await todos_db.read_state(row["slug"])
        if state and state.get("active_runner") == session_id:
            matches.append(row["slug"])
    if not matches:
        return None, project_path, "active-runner-not-found"
    if len(matches) > 1:
        return None, project_path, "active-runner-ambiguous"
    return matches[0], project_path, "ok"


async def hold_todo_for_manual_session_close(db: Db, session_id: str) -> ActiveRunnerMutationResult:
    slug, project_path, reason = await _active_runner_slug(db, session_id)
    if slug is None or project_path is None:
        logger.warning("manual session close could not correlate active_runner", session_id=session_id, reason=reason)
        return ActiveRunnerMutationResult(slug=slug, project_path=project_path, mutated=False, reason=reason)

    todos_db = await get_todos_db(project_path)
    state = await todos_db.read_state(slug)
    if state is None:
        return ActiveRunnerMutationResult(slug=slug, project_path=project_path, mutated=False, reason="state-not-found")
    writer = StateWriter(state)
    writer.state.hold = True
    writer.state.hold_audit = HoldAuditState(
        source="session_close",
        set_at=datetime.now(UTC).isoformat(),
        set_by_session_id=session_id,
        reason="manual session close",
    )
    await writer.commit(todos_db, slug)
    await _emit_todo_updated(slug=slug, project_path=project_path, source="workflow.session_close")
    return ActiveRunnerMutationResult(slug=slug, project_path=project_path, mutated=True, reason="held")


async def clear_active_runner_for_session_end(db: Db, session_id: str) -> ActiveRunnerMutationResult:
    slug, project_path, reason = await _active_runner_slug(db, session_id)
    if project_path is not None:
        await _emit_session_ended(session_id=session_id, project_path=project_path)
    if slug is None or project_path is None:
        return ActiveRunnerMutationResult(slug=slug, project_path=project_path, mutated=False, reason=reason)

    todos_db = await get_todos_db(project_path)
    state = await todos_db.read_state(slug)
    if state is None:
        return ActiveRunnerMutationResult(slug=slug, project_path=project_path, mutated=False, reason="state-not-found")
    writer = StateWriter(state)
    writer.state.active_runner = None
    writer.state.manually_started = False
    await writer.commit(todos_db, slug)
    return ActiveRunnerMutationResult(slug=slug, project_path=project_path, mutated=True, reason="cleared")


__all__ = [
    "ActiveRunnerMutationResult",
    "clear_active_runner_for_session_end",
    "hold_todo_for_manual_session_close",
]
