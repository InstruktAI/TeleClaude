"""Request-scoped identity pin for todo-store slug selection."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Protocol, cast

from sqlalchemy.sql import Select, Update

from teleclaude.core.todos_db._models import TODO_TABLE


@dataclass(frozen=True)
class TodoIdentityPin:
    """The exact todo row a slug-based store operation may select."""

    db_path: str
    slug: str
    todo_id: str


class _TodoStore(Protocol):
    """Store path needed to scope a pin to one project's database."""

    db_path: str


_IDENTITY_PIN: ContextVar[TodoIdentityPin | None] = ContextVar("todo_identity_pin", default=None)


@contextmanager
def todo_identity_pin(*, db_path: str, slug: str, todo_id: str) -> Iterator[None]:
    """Install and restore a row identity while delegated slug logic executes."""
    token: Token[TodoIdentityPin | None] = _IDENTITY_PIN.set(
        TodoIdentityPin(db_path=db_path, slug=slug, todo_id=todo_id)
    )
    try:
        yield
    finally:
        _IDENTITY_PIN.reset(token)


def get_todo_identity_pin() -> TodoIdentityPin | None:
    """Return the identity pin active in the current execution context."""
    return _IDENTITY_PIN.get()


def apply_todo_identity_pin[StatementT: Select[Any] | Update](
    statement: StatementT,
    store: _TodoStore,
    slug: str,
) -> StatementT:
    """Restrict a matching pinned slug query to its identified row."""
    pin = get_todo_identity_pin()
    if pin is None or pin.db_path != store.db_path or pin.slug != slug:
        return statement
    return cast(StatementT, statement.where(TODO_TABLE.c.id == pin.todo_id))
