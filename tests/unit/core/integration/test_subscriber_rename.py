"""Tests for integration subscription rewrite handling on todo rename events."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from teleclaude.core.integration.subscriber_rename import (
    IntegrationSubscriptionSubscriber,
    TodoRenamedSubscriptionEvent,
)

_OLD_SLUG = "old-slug"
_NEW_SLUG = "new-slug"
_OTHER_SLUG = "other-slug"
_RENAMED_AT = "2026-05-21T10:00:00Z"


def _create_subscriptions_table(connection: Connection) -> None:
    connection.execute(text("CREATE TABLE subscriptions (id INTEGER PRIMARY KEY, slug TEXT NOT NULL)"))


def _insert_subscription(connection: Connection, slug: str) -> None:
    connection.execute(text("INSERT INTO subscriptions (slug) VALUES (:slug)"), {"slug": slug})


def _subscription_slugs(connection: Connection) -> list[str]:
    return list(connection.execute(text("SELECT slug FROM subscriptions ORDER BY id")).scalars())


def _rename_event() -> TodoRenamedSubscriptionEvent:
    return TodoRenamedSubscriptionEvent(old_slug=_OLD_SLUG, new_slug=_NEW_SLUG, renamed_at=_RENAMED_AT)


def test_todo_renamed_rewrites_matching_subscription_rows_with_connection() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    subscriber = IntegrationSubscriptionSubscriber()

    with engine.begin() as connection:
        _create_subscriptions_table(connection)
        _insert_subscription(connection, _OLD_SLUG)
        _insert_subscription(connection, _OTHER_SLUG)
        _insert_subscription(connection, _OLD_SLUG)

    with engine.connect() as connection:
        result = subscriber.handle_todo_renamed(connection, _rename_event())
        slugs = _subscription_slugs(connection)

    assert result.rows_updated == 2
    assert slugs == [_NEW_SLUG, _OTHER_SLUG, _NEW_SLUG]


def test_todo_renamed_duplicate_event_does_not_rewrite_later_rows_with_session() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    subscriber = IntegrationSubscriptionSubscriber()

    with engine.begin() as connection:
        _create_subscriptions_table(connection)
        _insert_subscription(connection, _OLD_SLUG)

    with Session(engine) as session:
        first = subscriber.handle_todo_renamed(session, _rename_event())
        session.execute(text("INSERT INTO subscriptions (slug) VALUES (:slug)"), {"slug": _OLD_SLUG})
        duplicate = subscriber.handle_todo_renamed(session, _rename_event())
        session.commit()

    with engine.connect() as connection:
        slugs = _subscription_slugs(connection)

    assert first.rows_updated == 1
    assert duplicate.rows_updated == 0
    assert slugs == [_NEW_SLUG, _OLD_SLUG]
