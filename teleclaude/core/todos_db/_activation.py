"""The store's activation transaction: classify every item row, rewrite what the pass converts, record the mark.

The semantics of the classification belong to the workflow machine (``workflow_machine/activation.py``); the store owns
the transaction. The pass runs under the writer lock in one write transaction, reads the rows it classifies inside it,
and either commits every rewrite with the converted-row records and the mark, or writes nothing.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import ARTIFACT_DESIGN_SPEC, ARTIFACT_INPUT
from teleclaude.core.todos_db._activation_schema import (
    CONVERTED_TABLE,
    MARK_TABLE,
    activation_schema_in_place,
)
from teleclaude.core.todos_db._converted_rows import insert_converted_row
from teleclaude.core.todos_db._models import Todo, TodoStateModel
from teleclaude.core.todos_db._upcycle import canonicalize_state_for_storage
from teleclaude.core.todos_db._workflow_operations import immediate_transaction
from teleclaude.core.workflow_store.types import ActivationRefused, ActivationRow, RowRewrite

ACTIVE_STATUSES = ("active", "icebox")
SCHEMA_MISSING = "the converted-row record or the enforcement of its predicates is not in place"

_INSERT_MARK = f"INSERT OR IGNORE INTO {MARK_TABLE} (id, activated_at) VALUES (1, :activated_at)"
_SELECT_CONVERTED = f"SELECT row_id FROM {CONVERTED_TABLE}"


class _ActivationHost(Protocol):
    db_path: str

    def _session(self) -> AbstractAsyncContextManager[SqlAsyncSession]: ...

    async def artifact_digest_in_session(self, slug: str, name: str, session: SqlAsyncSession) -> str: ...

    def on_committed(self, event_hint: str, event_data: object | None = None) -> None: ...


def _schema_and_mark(db_path: str) -> tuple[bool, bool]:
    """Whether the schema is in place and whether the store is marked, read on a short connection of their own."""
    conn = sqlite3.connect(db_path)
    try:
        in_place = activation_schema_in_place(conn)
        marked = (
            in_place and conn.execute(f"SELECT 1 FROM {MARK_TABLE} WHERE id = 1").fetchone() is not None
        )  # guard: raw-sql
        return in_place, bool(marked)
    finally:
        conn.close()


async def fetch_activation_rows(
    host: _ActivationHost, session: SqlAsyncSession, *, row_id: str | None = None
) -> list[ActivationRow]:
    """The active and icebox item rows with the facts a classification reads, optionally just one row."""
    connection = await session.connection()
    converted = {row[0] for row in (await connection.execute(text(_SELECT_CONVERTED))).all()}  # guard: raw-sql
    statement = select(Todo, TodoStateModel).where(Todo.id == TodoStateModel.id, Todo.status.in_(ACTIVE_STATUSES))  # type: ignore[attr-defined]
    if row_id is not None:
        statement = statement.where(Todo.id == row_id)
    rows: list[ActivationRow] = []
    for todo, state_model in (await session.exec(statement)).all():
        slug = str(todo.slug)
        rows.append(
            ActivationRow(
                row_id=str(todo.id),
                slug=slug,
                status=str(todo.status),
                state=json.loads(state_model.state),
                has_input=bool(await host.artifact_digest_in_session(slug, ARTIFACT_INPUT, session)),
                has_design_spec=bool(await host.artifact_digest_in_session(slug, ARTIFACT_DESIGN_SPEC, session)),
                converted=str(todo.id) in converted,
            )
        )
    return rows


async def apply_rewrite(session: SqlAsyncSession, rewrite: RowRewrite, now: str) -> None:
    """Write one row's rewritten state and, when it converts the row, its converted-row record."""
    model = await session.get(TodoStateModel, rewrite.row_id)
    if model is None:
        raise ActivationRefused(f"row {rewrite.row_id} vanished while the pass classified it")
    model.state = json.dumps(canonicalize_state_for_storage(rewrite.state))
    model.updated_at = now
    session.add(model)
    await session.flush()
    if rewrite.converted_from:
        await insert_converted_row(session, rewrite.row_id, rewrite.converted_from, rewrite.path.value, at=now)


class TodosDbActivationMixin:
    """The activation mark and the transaction that records it."""

    def read_activation_sync(self: _ActivationHost) -> tuple[bool, bool]:
        """The same reading for a caller on a worker thread."""
        return _schema_and_mark(self.db_path)

    async def read_activation(self: _ActivationHost) -> tuple[bool, bool]:
        """Whether the converted-row schema is in place and whether the store carries the completion mark."""
        return await asyncio.to_thread(_schema_and_mark, self.db_path)

    async def run_activation(
        self: _ActivationHost,
        classify: Callable[[list[ActivationRow]], list[RowRewrite]],
        verify: Callable[[list[ActivationRow]], None],
        *,
        mark: bool,
    ) -> int:
        """Classify the rows inside one write transaction, apply the rewrites, verify, and record the mark if asked.

        ``classify`` and ``verify`` raise ``ActivationRefused`` to write nothing. The rewrites and their converted-row
        records commit together with the mark, or none of them does.
        """
        in_place, _ = await asyncio.to_thread(_schema_and_mark, self.db_path)
        if not in_place:
            raise ActivationRefused(SCHEMA_MISSING)
        now = datetime.now(UTC).isoformat()
        async with immediate_transaction(self) as session:  # type: ignore[arg-type]
            rewrites = classify(await fetch_activation_rows(self, session))
            for rewrite in rewrites:
                await apply_rewrite(session, rewrite, now)
            verify(await fetch_activation_rows(self, session))
            if mark:
                connection = await session.connection()
                await connection.execute(text(_INSERT_MARK), {"activated_at": now})  # guard: raw-sql
        if rewrites:
            self.on_committed("todo_updated")
        return len(rewrites)
