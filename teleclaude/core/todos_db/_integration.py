"""Local persistence operations owned by the serial workflow integrator."""

from __future__ import annotations

import sqlite3
from typing import Protocol, cast


class _SyncConnectionHost(Protocol):
    def _sync_conn(self) -> sqlite3.Connection: ...


class TodosDbIntegrationMixin:
    """Dependency and delivery reads/writes for existing integration flow."""

    def downstream_dependency_slugs_sync(self, slug: str) -> list[str]:
        """Return every direct dependent, preserving dependency row order."""
        connection = cast(_SyncConnectionHost, self)._sync_conn()
        try:
            rows = connection.execute(
                "SELECT slug FROM todo_deps WHERE depends_on = ?",  # guard: raw-sql
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
        connection = cast(_SyncConnectionHost, self)._sync_conn()
        try:
            connection.execute(
                "DELETE FROM todo_deps WHERE depends_on = ?",  # guard: raw-sql
                (slug,),
            )
            connection.commit()
        finally:
            connection.close()
