"""Wall-clock bounded admission to the working copy's single SQLite writer.

SQLite's native busy wait is a nominal budget, not a wall-clock bound, so a contender behind a long
GitHub-backed hold gives up late and unpredictably. A store opted into this admission waits for the
writer in short native slices and retries until a monotonic deadline, then refuses with
`WorkingCopyWriteRefused` instead of a raw driver error.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

import aiosqlite
from sqlalchemy import Engine, event

# The three limits the working-copy waits are sized against. The push deadline H must not exceed the
# admission budget A, so a contender queued behind one holder that respects H is admitted; the request
# deadline R must end inside the CLI caller's default wait (`teleclaude/cli/tool_client.py`).
WRITE_ADMISSION_BUDGET_S: Final = 15.0
PUSH_DEADLINE_S: Final = 12.0
REQUEST_DEADLINE_S: Final = 25.0

_BUSY_SLICE_S: Final = 0.01
_BUSY_SLICE_MS: Final = int(_BUSY_SLICE_S * 1000)
_BUSY_TIMEOUT_SQL: Final = f"PRAGMA busy_timeout = {_BUSY_SLICE_MS}"
_BEGIN_IMMEDIATE_SQL: Final = "BEGIN IMMEDIATE"
_SQLITE_ERROR_CODE_ATTRIBUTE: Final = "sqlite_errorcode"
_DRIVER_CONNECTION_ATTRIBUTE: Final = "driver_connection"
_REFUSAL_MESSAGE: Final = "the working copy's writer stayed busy past the admission deadline"


class _EngineEvent(StrEnum):
    """Closed set of SQLAlchemy engine events the admission listens to."""

    CONNECT = "connect"
    DO_EXECUTE = "do_execute"
    DO_EXECUTEMANY = "do_executemany"
    COMMIT = "commit"


class WorkingCopyWriteRefused(RuntimeError):
    """A working-copy wait ran out before the write was admitted or while its push was under way.

    `request_saved` says an earlier transaction of the same API request committed. `commit_point_sent`
    says the refused push had already sent its commit-point write to GitHub, so the change may have
    been saved there. Neither set means the refused transaction wrote nothing anywhere.
    """

    def __init__(self, *, request_saved: bool = False, commit_point_sent: bool = False) -> None:
        super().__init__(_REFUSAL_MESSAGE)
        self.request_saved = request_saved
        self.commit_point_sent = commit_point_sent


@dataclass
class RequestScope:
    """The working-copy deadline of one API request, honoured only by the task that entered it."""

    deadline: float
    owner: asyncio.Task[Any] | None
    committed: bool = False


_scope: ContextVar[RequestScope | None] = ContextVar("working_copy_request_scope", default=None)


def _current_task() -> asyncio.Task[Any] | None:
    try:
        return asyncio.current_task()
    except RuntimeError:
        return None


@contextmanager
def request_deadline(seconds: float = REQUEST_DEADLINE_S) -> Iterator[RequestScope]:
    """Bound the working-copy waits of the current task's request by one shared deadline."""
    scope = RequestScope(deadline=time.monotonic() + seconds, owner=_current_task())
    previous = _scope.get()
    _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.set(previous)


def owned_request_scope() -> RequestScope | None:
    """Return the active request scope only inside the task that entered it."""
    scope = _scope.get()
    if scope is None or scope.owner is None or scope.owner is not _current_task():
        return None
    return scope


def bounded_deadline(budget: float) -> float:
    """Return the monotonic deadline for one wait: the budget, or the request's end if sooner."""
    deadline = time.monotonic() + budget
    scope = owned_request_scope()
    return deadline if scope is None else min(deadline, scope.deadline)


def refuse_write(*, commit_point_sent: bool = False) -> WorkingCopyWriteRefused:
    """Build the store's refusal, stating whether an earlier transaction of the request committed."""
    scope = owned_request_scope()
    return WorkingCopyWriteRefused(
        request_saved=scope is not None and scope.committed, commit_point_sent=commit_point_sent
    )


def _is_busy(error: sqlite3.OperationalError) -> bool:
    """Whether the writer was merely contended: retrying can succeed (a stale snapshot never does)."""
    code = getattr(error, _SQLITE_ERROR_CODE_ATTRIBUTE, None)
    return code is not None and code == sqlite3.SQLITE_BUSY


def _driver_connection(dbapi_connection: Any) -> Any:
    return getattr(dbapi_connection, _DRIVER_CONNECTION_ATTRIBUTE, dbapi_connection)


def _admit_statement(cursor: Any, statement: str, parameters: Any, context: Any, *, many: bool, budget: float) -> None:
    """Run one statement, retrying a busy refusal until the deadline while no write has happened yet."""
    in_transaction = bool(_driver_connection(context.root_connection.connection).in_transaction)
    deadline = bounded_deadline(budget)
    while True:
        try:
            if many:
                cursor.executemany(statement, parameters)
            else:
                cursor.execute(statement, parameters)
            return
        except sqlite3.OperationalError as error:
            if not _is_busy(error) or in_transaction:
                raise
            if time.monotonic() >= deadline:
                raise refuse_write() from error


def attach_write_admission(engine: Engine, budget: float) -> None:
    """Make every write on this engine wait for the writer up to `budget` seconds of wall time."""

    def short_busy_slice(dbapi_connection: Any, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(_BUSY_TIMEOUT_SQL)
        finally:
            cursor.close()

    def execute(cursor: Any, statement: str, parameters: Any, context: Any) -> bool:
        _admit_statement(cursor, statement, parameters, context, many=False, budget=budget)
        return True

    def executemany(cursor: Any, statement: str, parameters: Any, context: Any) -> bool:
        _admit_statement(cursor, statement, parameters, context, many=True, budget=budget)
        return True

    def note_commit(connection: Any) -> None:
        scope = owned_request_scope()
        if scope is not None and _driver_connection(connection.connection).in_transaction:
            scope.committed = True

    event.listen(engine, _EngineEvent.CONNECT, short_busy_slice)
    event.listen(engine, _EngineEvent.DO_EXECUTE, execute, retval=True)
    event.listen(engine, _EngineEvent.DO_EXECUTEMANY, executemany, retval=True)
    event.listen(engine, _EngineEvent.COMMIT, note_commit)


def connect_admitted(db_path: str, budget: float) -> sqlite3.Connection:
    """Open a raw connection that holds the writer, waiting for it up to `budget` seconds of wall time."""
    connection = sqlite3.connect(db_path, timeout=_BUSY_SLICE_S)
    deadline = bounded_deadline(budget)
    try:
        while True:
            try:
                connection.execute(_BEGIN_IMMEDIATE_SQL)
                return connection
            except sqlite3.OperationalError as error:
                if not _is_busy(error):
                    raise
                if time.monotonic() >= deadline:
                    raise refuse_write() from error
    except BaseException:
        connection.close()
        raise


async def connect_admitted_async(db_path: str, budget: float) -> Any:
    """Async sibling of `connect_admitted` over aiosqlite; every wait happens in the driver's thread."""
    connection = await aiosqlite.connect(db_path, timeout=_BUSY_SLICE_S)
    deadline = bounded_deadline(budget)
    try:
        while True:
            try:
                await connection.execute(_BEGIN_IMMEDIATE_SQL)
                return connection
            except sqlite3.OperationalError as error:
                if not _is_busy(error):
                    raise
                if time.monotonic() >= deadline:
                    raise refuse_write() from error
    except BaseException:
        await connection.close()
        raise
