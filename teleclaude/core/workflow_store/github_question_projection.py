"""Expire GitHub question assignments when their phase or human response advances."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from teleclaude.core.db import db
from teleclaude.core.human_involvement import latest_human_input_at
from teleclaude.core.todos_db._adapter import TodosDb
from teleclaude.core.todos_db._github_questions import awaiting_questions, close_awaiting_question
from teleclaude.core.todos_db._working_copy import (
    WorkingCopyItemSnapshot,
    acquire_repository_writer,
    item_snapshot,
    mark_reflection_owed,
)
from teleclaude.core.workflow_store.github_record import WorkflowField
from teleclaude.core.workflow_store.github_reflection import github_handles_for_person_slugs


def waiting_person_slugs(session: Session, item_id: str, phase: str | None) -> tuple[str, ...]:
    """Return unique recipients whose unanswered question belongs to the current phase."""
    if phase is None:
        return ()
    return tuple(
        dict.fromkeys(
            slug
            for question in awaiting_questions(session, item_id)
            if question.phase == phase
            for slug in question.recipient_slugs
        )
    )


def waiting_person_handles(session: Session, item_id: str, snapshot: WorkingCopyItemSnapshot) -> tuple[str, ...]:
    """Return handles for unresolved questions whose recorded phase still matches the item."""
    return github_handles_for_person_slugs(waiting_person_slugs(session, item_id, _lifecycle_phase(snapshot)))


async def close_resolved_questions(store: TodosDb) -> None:
    """Close questions whose item phase moved or whose asking session received newer human input."""
    async with store._session() as read_session:
        questions = await read_session.run_sync(awaiting_questions)
        closed: list[tuple[int, str]] = []
        for question in questions:

            def read_snapshot(session: Session, target: str = question.item_id) -> WorkingCopyItemSnapshot | None:
                return item_snapshot(session, target)

            snapshot = await read_session.run_sync(read_snapshot)
            if snapshot is None:
                closed.append((question.question_id, question.item_id))
                continue
            phase = _lifecycle_phase(snapshot)
            if phase != question.phase:
                closed.append((question.question_id, question.item_id))
                continue
            asking_session = await db.get_session(question.session_id)
            latest_input = latest_human_input_at(asking_session) if asking_session is not None else None
            try:
                asked_at = datetime.fromisoformat(question.asked_at)
            except ValueError:
                continue
            if asked_at.tzinfo is None:
                asked_at = asked_at.replace(tzinfo=UTC)
            if latest_input is not None and latest_input > asked_at:
                closed.append((question.question_id, question.item_id))
    if not closed:
        return
    closed_at = datetime.now(UTC).isoformat()

    async with store._session() as write_session:
        async with write_session.begin():
            await write_session.run_sync(acquire_repository_writer)

            def remove_questions(session: Session) -> None:
                for question_id, item_id in closed:
                    close_awaiting_question(session, question_id, closed_at)
                    mark_reflection_owed(session, item_id)

            await write_session.run_sync(remove_questions)


def _lifecycle_phase(snapshot: WorkingCopyItemSnapshot) -> str | None:
    if snapshot.state is None:
        return None
    value = snapshot.state.get(WorkflowField.STATE)
    if not isinstance(value, str):
        return None
    try:
        state = json.loads(value)
    except json.JSONDecodeError:
        return None
    phase = state.get(WorkflowField.LIFECYCLE_PHASE) if isinstance(state, dict) else None
    return phase if isinstance(phase, str) else None
