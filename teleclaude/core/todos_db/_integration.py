"""Local persistence operations owned by the serial workflow integrator."""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from typing import Protocol, cast

from sqlmodel import Session

_DOWNSTREAM_DEPENDENCIES_QUERY = "SELECT slug FROM todo_deps WHERE depends_on = ?"
_DELETE_DEPENDENCY_REFERENCES_QUERY = "DELETE FROM todo_deps WHERE depends_on = ?"


class _SyncConnectionHost(Protocol):
    def _sync_conn(self) -> sqlite3.Connection: ...


class _CommitCallbackHost(Protocol):
    _before_commit_callback: object | None

    def _sync_session(self) -> AbstractContextManager[Session]: ...


class TodosDbIntegrationMixin:
    """Dependency and delivery reads/writes for existing integration flow."""

    def downstream_dependency_slugs_sync(self, slug: str) -> list[str]:
        """Return every direct dependent, preserving dependency row order."""
        connection = cast(_SyncConnectionHost, self)._sync_conn()
        try:
            rows = connection.execute(
                _DOWNSTREAM_DEPENDENCIES_QUERY,  # guard: raw-sql
                (slug,),
            ).fetchall()
        finally:
            connection.close()
        return [str(row[0]) for row in rows if isinstance(row[0], str)]

    def clean_dep_references_sync(self, slug: str) -> None:
        """Synchronously remove dependency references after integration delivery.

        This intentionally retains the integrator's existing raw-connection
        commit boundary and does not emit another mutation notification.
        """
        host = cast(_CommitCallbackHost, self)
        if host._before_commit_callback is not None:
            with host._sync_session() as session:
                session.connection().exec_driver_sql(
                    _DELETE_DEPENDENCY_REFERENCES_QUERY,  # guard: raw-sql
                    (slug,),
                )
                session.commit()
            return
        connection = cast(_SyncConnectionHost, self)._sync_conn()
        try:
            connection.execute(
                _DELETE_DEPENDENCY_REFERENCES_QUERY,  # guard: raw-sql
                (slug,),
            )
            connection.commit()
        finally:
            connection.close()
