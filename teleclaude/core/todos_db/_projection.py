"""Typed local read model for the workflow todo projection."""

from __future__ import annotations

import json
import time
from typing import Any, cast

from teleclaude.constants import TodoStatus
from teleclaude.core.workflow_store.types import (
    ArtifactFile,
    StoreAddress,
    TodoProjectionItem,
    TodoProjectionMetrics,
    TodoProjectionSnapshot,
    WorkItemId,
)
from teleclaude.types.state_value import StateValue

from ._upcycle import upcycle_state_dict


class TodosDbProjectionMixin:
    """Read workflow projection facts without exposing SQLite to consumers."""

    def read_todo_projection_snapshot_sync(self, statuses: tuple[TodoStatus, ...]) -> TodoProjectionSnapshot:
        db = cast(Any, self)
        connection_started = time.perf_counter()
        connection = db._sync_conn()
        connection_seconds = time.perf_counter() - connection_started
        try:
            placeholders = ", ".join("?" for _ in statuses)
            item_started = time.perf_counter()
            rows = connection.execute(
                "SELECT id, slug, ready_since, schedule, group_id, description, status, "
                "delivered_at, updated_at, created_at, removed_at, lineage, entry_point, "
                f"human_involved, context FROM todo WHERE status IN ({placeholders}) ORDER BY id",  # guard: raw-sql
                tuple(status.value for status in statuses),
            ).fetchall()
            item_query_seconds = time.perf_counter() - item_started

            delivered_rows = connection.execute(
                "SELECT slug FROM todo WHERE status = 'delivered'",  # guard: raw-sql
            ).fetchall()
            delivered_items = frozenset(WorkItemId(str(row[0])) for row in delivered_rows if isinstance(row[0], str))

            dependency_started = time.perf_counter()
            dependency_rows = connection.execute(
                "SELECT slug, depends_on FROM todo_deps",  # guard: raw-sql
            ).fetchall()
            dependencies: dict[WorkItemId, list[WorkItemId]] = {}
            for dependent, prerequisite in dependency_rows:
                if isinstance(dependent, str) and isinstance(prerequisite, str):
                    dependencies.setdefault(WorkItemId(dependent), []).append(WorkItemId(prerequisite))
            dependency_query_seconds = time.perf_counter() - dependency_started

            holders = connection.execute(
                "SELECT id, slug FROM todo WHERE status = 'holder'",  # guard: raw-sql
            ).fetchall()
            structural_group_slugs = {
                StoreAddress(str(row_id)): WorkItemId(str(slug))
                for row_id, slug in holders
                if isinstance(row_id, str) and isinstance(slug, str)
            }

            state_query_seconds = 0.0
            artifact_query_seconds = 0.0
            item_build_seconds = 0.0
            items: list[TodoProjectionItem] = []
            for row in rows:
                item_started = time.perf_counter()
                row_id, slug = row[0], row[1]
                state_started = time.perf_counter()
                state_row = connection.execute(
                    "SELECT state FROM todo_state WHERE id = ?",  # guard: raw-sql
                    (row_id,),
                ).fetchone()
                state_query_seconds += time.perf_counter() - state_started

                state: dict[str, StateValue] | None = None
                state_error: str | None = None
                if state_row is not None:
                    try:
                        raw_state = cast(dict[str, StateValue], json.loads(state_row[0]))
                        state = upcycle_state_dict(raw_state)
                    except ValueError as error:
                        state_error = str(error)

                artifact_started = time.perf_counter()
                has_requirements = (
                    connection.execute(
                        "SELECT 1 FROM todo_artifacts WHERE id = ? AND name = 'requirements'",  # guard: raw-sql
                        (row_id,),
                    ).fetchone()
                    is not None
                )
                has_implementation_plan = (
                    connection.execute(
                        "SELECT 1 FROM todo_artifacts WHERE id = ? AND name = 'implementation-plan'",  # guard: raw-sql
                        (row_id,),
                    ).fetchone()
                    is not None
                )
                artifact_rows = connection.execute(
                    "SELECT name, updated_at FROM todo_artifacts WHERE id = ? ORDER BY name",  # guard: raw-sql
                    (row_id,),
                ).fetchall()
                version_row = connection.execute(
                    "SELECT COUNT(*) FROM todo_artifact_versions WHERE id = ?",  # guard: raw-sql
                    (row_id,),
                ).fetchone()
                artifact_query_seconds += time.perf_counter() - artifact_started

                items.append(
                    TodoProjectionItem(
                        item_id=WorkItemId(str(slug)),
                        store_address=StoreAddress(str(row_id)),
                        ready_since=row[2],
                        schedule=row[3],
                        group_address=StoreAddress(str(row[4])) if row[4] is not None else None,
                        description=row[5],
                        status=str(row[6]),
                        delivered_at=row[7],
                        updated_at=row[8],
                        created_at=row[9],
                        removed_at=row[10],
                        lineage=row[11],
                        entry_point=row[12],
                        human_involved=bool(row[13]),
                        context=row[14],
                        state=state,
                        state_error=state_error,
                        has_requirements=has_requirements,
                        has_implementation_plan=has_implementation_plan,
                        artifact_files=tuple(
                            ArtifactFile(str(name), timestamp if isinstance(timestamp, str) else None)
                            for name, timestamp in artifact_rows
                        ),
                        version_total=int(version_row[0]) if version_row is not None else 0,
                    )
                )
                item_build_seconds += time.perf_counter() - item_started

            metrics = TodoProjectionMetrics(
                init_seconds=0.0,
                connection_seconds=connection_seconds,
                item_query_seconds=item_query_seconds,
                dependency_query_seconds=dependency_query_seconds,
                state_query_seconds=state_query_seconds,
                artifact_query_seconds=artifact_query_seconds,
                item_build_seconds=item_build_seconds,
            )
            return TodoProjectionSnapshot(tuple(items), delivered_items, dependencies, structural_group_slugs, metrics)
        finally:
            connection.close()
