"""Functional tests for todo removal purge-time snippet reconciliation.

Spec: docs/project/spec/feature/workflow/todo-removal.md
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

import teleclaude.services.maintenance_service as maintenance_service_mod
from teleclaude.config import config
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.output_poller import OutputPoller
from teleclaude.core.todos_db import close_todos_db_instances, get_todos_db, todos_db_path
from teleclaude.docs_reconcile import reconcile_snippets_for_purged_slugs
from teleclaude.services.maintenance_service import MaintenanceService

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/todo-removal"


def _write_snippet(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
description: Purge fixture.
---
{body}
""",
        encoding="utf-8",
    )


@pytest.mark.spec(_SPEC, "UC-TR-PURGE-STRIPS-INBODY-MARKERS")
def test_purge_abandons_in_body_markers_for_purged_slug(tmp_path: Path, snapshot: object) -> None:
    snippet = tmp_path / "docs" / "project" / "spec" / "feature" / "context" / "purge-target.md"
    _write_snippet(
        snippet,
        """# Purge Target — Spec

## Canonical fields

Before.

<!-- planned:purged-slug -->
Abandoned addition.
<!-- /planned:purged-slug -->

<!-- planned-change:purged-slug -->
Original paragraph.
<!-- change:purged-slug -->
Replacement paragraph.
<!-- /planned-change:purged-slug -->

<!-- planned:other-slug -->
Other addition.
<!-- /planned:other-slug -->

After.
""",
    )

    plans = reconcile_snippets_for_purged_slugs(tmp_path, ["purged-slug"], {})

    # The snapshot pins the abandon fold: the purged slug's planned ADD block is
    # dropped with its content, its planned-change reverts to the original side, and
    # the other slug's marker survives untouched.
    assert [plan.path.name for plan in plans] == ["purge-target.md"]
    assert plans[0].rendered_content == snapshot


def test_purge_leaves_snippets_without_the_slug_untouched(tmp_path: Path) -> None:
    snippet = tmp_path / "docs" / "project" / "spec" / "feature" / "context" / "unrelated.md"
    _write_snippet(
        snippet,
        "# Unrelated — Spec\n\n## Canonical fields\n\n"
        "<!-- planned:other-slug -->\nOther addition.\n<!-- /planned:other-slug -->\n",
    )

    plans = reconcile_snippets_for_purged_slugs(tmp_path, ["purged-slug"], {})

    assert plans == []


def _backdate_removed_at(project_root: Path, slug: str, *, days: int) -> None:
    """Age a soft-removed row's tombstone so the retention sweep sees it as expired."""
    removed_at = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(todos_db_path(project_root))
    try:
        conn.execute("UPDATE todo SET removed_at = ? WHERE slug = ?", (removed_at, slug))
        conn.commit()
    finally:
        conn.close()


def _todo_row_count(project_root: Path, slug: str) -> int:
    """Count durable todo rows for a slug, tombstoned ones included."""
    conn = sqlite3.connect(todos_db_path(project_root))
    try:
        return conn.execute("SELECT COUNT(*) FROM todo WHERE slug = ?", (slug,)).fetchone()[0]
    finally:
        conn.close()


@pytest.mark.spec(_SPEC, "UC-TR-RETENTION-INDEPENDENT")
@pytest.mark.asyncio
async def test_removed_todo_purges_while_same_age_closed_session_is_retained(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cluster_event_bus: None,
) -> None:
    """At 8 days, the removed todo is past its window while the closed session is not."""
    del cluster_event_bus
    slug = "retention-independence-probe"
    session_id = "4c2b9d70-5555-4000-8000-000000000006"
    age = timedelta(days=8)

    project_root = tmp_path / "project"
    (project_root / ".teleclaude").mkdir(parents=True)
    await close_todos_db_instances()
    todos_db = await get_todos_db(project_root)
    await todos_db.add_to_todo(slug, lineage="human:test@example.com")
    await todos_db.soft_remove_from_todo(slug, cwd=str(project_root))
    _backdate_removed_at(project_root, slug, days=8)

    await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name=f"tc-{session_id}",
        last_input_origin="terminal",
        title="retention probe",
        session_id=session_id,
        emit_session_started=False,
    )
    await api.db.update_session(
        session_id,
        closed_at=datetime.now(UTC) - age,
        lifecycle_status="closed",
    )

    monkeypatch.setattr(maintenance_service_mod, "db", api.db)
    monkeypatch.setattr(
        config.computer,
        "get_all_trusted_dirs",
        lambda: [SimpleNamespace(path=str(project_root))],
    )
    service = MaintenanceService(
        client=get_command_service().client,
        output_poller=cast(OutputPoller, AsyncMock()),
        poller_watch_interval_s=1.0,
    )

    await service._cleanup_removed_todos()  # pyright: ignore[reportPrivateUsage]
    await service._cleanup_inactive_sessions()  # pyright: ignore[reportPrivateUsage]

    # The removed todo's 7-day window has elapsed: its durable row is hard-purged,
    # not merely tombstoned. The closed session's 90-day window has not.
    assert _todo_row_count(project_root, slug) == 0
    assert await api.db.get_session(session_id) is not None
