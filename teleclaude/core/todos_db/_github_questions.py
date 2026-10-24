"""Persist and resolve GitHub issue questions that temporarily assign a work item."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import text
from sqlalchemy.orm import Session

_QUESTION_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS github_awaiting_question ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL, session_id TEXT NOT NULL, "
    "asked_at TEXT NOT NULL, phase TEXT NOT NULL, recipient_slugs TEXT NOT NULL, closed_at TEXT)"
)
_QUESTION_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS github_awaiting_question_item ON github_awaiting_question(item_id, id)"
)
_INSERT_QUESTION_SQL = (
    "INSERT INTO github_awaiting_question(item_id, session_id, asked_at, phase, recipient_slugs) "
    "VALUES (:item_id, :session_id, :asked_at, :phase, :recipient_slugs)"
)
_OPEN_QUESTIONS_SQL = (
    "SELECT id, item_id, session_id, asked_at, phase, recipient_slugs "
    "FROM github_awaiting_question WHERE item_id = :item_id AND closed_at IS NULL ORDER BY id"
)
_ALL_OPEN_QUESTIONS_SQL = (
    "SELECT id, item_id, session_id, asked_at, phase, recipient_slugs "
    "FROM github_awaiting_question WHERE closed_at IS NULL ORDER BY id"
)
_CLOSE_QUESTION_SQL = "UPDATE github_awaiting_question SET closed_at = :closed_at WHERE id = :id AND closed_at IS NULL"


class QuestionField(StrEnum):
    """Closed set of question-bookkeeping columns and SQL bind names."""

    ID = "id"
    ITEM_ID = "item_id"
    SESSION_ID = "session_id"
    ASKED_AT = "asked_at"
    PHASE = "phase"
    RECIPIENT_SLUGS = "recipient_slugs"
    CLOSED_AT = "closed_at"


@dataclass(frozen=True)
class AwaitingQuestion:
    """An issue comment whose recipients still own the next human response."""

    question_id: int
    item_id: str
    session_id: str
    asked_at: str
    phase: str
    recipient_slugs: tuple[str, ...]


def initialize_question_bookkeeping(connection: sqlite3.Connection) -> None:
    """Install question bookkeeping beside the GitHub working-copy tables."""
    connection.execute(_QUESTION_TABLE_DDL)
    connection.execute(_QUESTION_INDEX_DDL)


def insert_awaiting_question(
    session: Session,
    *,
    item_id: str,
    session_id: str,
    asked_at: str,
    phase: str,
    recipient_slugs: tuple[str, ...],
) -> None:
    """Record the recipients waiting for this item's next phase response."""
    session.execute(
        text(_INSERT_QUESTION_SQL),
        {
            QuestionField.ITEM_ID: item_id,
            QuestionField.SESSION_ID: session_id,
            QuestionField.ASKED_AT: asked_at,
            QuestionField.PHASE: phase,
            QuestionField.RECIPIENT_SLUGS: json.dumps(list(recipient_slugs)),
        },
    )


def awaiting_questions(session: Session, item_id: str | None = None) -> tuple[AwaitingQuestion, ...]:
    """Read open questions for one item, or all items when omitted."""
    statement = _OPEN_QUESTIONS_SQL if item_id is not None else _ALL_OPEN_QUESTIONS_SQL
    parameters = {QuestionField.ITEM_ID.value: item_id} if item_id is not None else {}
    rows = session.execute(text(statement), parameters).mappings().all()
    questions: list[AwaitingQuestion] = []
    for row in rows:
        recipient_value = row[QuestionField.RECIPIENT_SLUGS]
        try:
            parsed: object = json.loads(recipient_value) if isinstance(recipient_value, str) else []
        except json.JSONDecodeError:
            parsed = []
        recipients = tuple(value for value in parsed if isinstance(value, str)) if isinstance(parsed, list) else ()
        questions.append(
            AwaitingQuestion(
                question_id=int(row[QuestionField.ID]),
                item_id=str(row[QuestionField.ITEM_ID]),
                session_id=str(row[QuestionField.SESSION_ID]),
                asked_at=str(row[QuestionField.ASKED_AT]),
                phase=str(row[QuestionField.PHASE]),
                recipient_slugs=recipients,
            )
        )
    return tuple(questions)


def close_awaiting_question(session: Session, question_id: int, closed_at: str) -> None:
    """Close one question after its phase changes or its asking session receives human input."""
    session.execute(text(_CLOSE_QUESTION_SQL), {QuestionField.ID: question_id, QuestionField.CLOSED_AT: closed_at})
