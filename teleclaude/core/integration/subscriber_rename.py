"""Integration rename subscriber for slug-keyed ancillary state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

SubscriptionBind = Connection | Session
RenameIdempotencyKey = tuple[str, str, str]


@dataclass(frozen=True)
class TodoRenamedSubscriptionEvent:
    """Payload required to rewrite slug-keyed subscription rows."""

    old_slug: str
    new_slug: str
    renamed_at: str

    def __post_init__(self) -> None:
        if not self.old_slug:
            raise ValueError("old_slug must be non-empty")
        if not self.new_slug:
            raise ValueError("new_slug must be non-empty")
        if not self.renamed_at:
            raise ValueError("renamed_at must be non-empty")

    @property
    def idempotency_key(self) -> RenameIdempotencyKey:
        """Return the event identity used to deduplicate rename handling."""
        return (self.old_slug, self.new_slug, self.renamed_at)


@dataclass(frozen=True)
class SubscriptionRewriteResult:
    """Outcome of applying a rename event to subscription rows."""

    status: Literal["applied", "duplicate"]
    rows_updated: int


class IntegrationSubscriptionSubscriber:
    """Handle integration events that affect subscription rows."""

    def __init__(self) -> None:
        self._processed_renames: set[RenameIdempotencyKey] = set()

    def handle_todo_renamed(
        self,
        bind: SubscriptionBind,
        event: TodoRenamedSubscriptionEvent,
    ) -> SubscriptionRewriteResult:
        """Rewrite slug-keyed subscriptions for a todo rename event."""
        idempotency_key = event.idempotency_key
        if idempotency_key in self._processed_renames:
            return SubscriptionRewriteResult(status="duplicate", rows_updated=0)

        rows_updated = _rewrite_subscription_slugs(bind, old_slug=event.old_slug, new_slug=event.new_slug)
        self._processed_renames.add(idempotency_key)
        return SubscriptionRewriteResult(status="applied", rows_updated=rows_updated)


def _rewrite_subscription_slugs(bind: SubscriptionBind, *, old_slug: str, new_slug: str) -> int:
    statement = text("UPDATE subscriptions SET slug = :new_slug WHERE slug = :old_slug")
    params = {"old_slug": old_slug, "new_slug": new_slug}

    def _execute() -> int:
        result = bind.execute(statement, params)
        rowcount = getattr(result, "rowcount", 0)
        return rowcount if isinstance(rowcount, int) else 0

    if bind.in_transaction():
        return _execute()

    with bind.begin():
        return _execute()
