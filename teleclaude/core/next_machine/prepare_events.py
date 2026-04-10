"""Prepare state machine — lifecycle events and artifact checks.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import PreparePhase
from teleclaude.events.envelope import EventLevel
from teleclaude.events.producer import emit_event
from teleclaude.project_root import resolve_main_repo_root
from teleclaude.session_identity import get_session_id


def _emit_prepare_event(event_type: str, payload: dict[str, str | list[str]]) -> None:
    """Fire-and-forget lifecycle event emission for prepare state machine."""

    async def _emit() -> None:
        try:
            slug = str(payload.get("slug", ""))
            description = f"prepare.{event_type.split('.')[-1]}: {slug}"
            await emit_event(
                event=event_type,
                source=f"orchestrator/{(get_session_id() or 'unknown')}",
                level=EventLevel.WORKFLOW,
                domain="software-development",
                description=description,
                entity=slug,
                payload=dict(payload),
            )
        except Exception:  # pylint: disable=broad-exception-caught
            pass  # Never block prepare on event emission failure

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_emit(), name="prepare-event-emit")
    except RuntimeError:
        # No running loop (thread or sync CLI context) — fire-and-forget via new event loop
        try:
            asyncio.run(_emit())
        except Exception:  # pylint: disable=broad-exception-caught
            pass  # Never block prepare on event emission failure


def _has_test_spec_artifacts(cwd: str, slug: str) -> bool:
    """Check if xfail-marked test spec files exist in the worktree."""
    worktree_path = Path(cwd) / WORKTREE_DIR / slug
    if not worktree_path.is_dir():
        return False
    # Look for test files containing xfail markers
    for test_file in worktree_path.rglob("test_*.py"):
        try:
            content = test_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if "xfail" in content:
            return True
    return False


def invalidate_stale_preparations(cwd: str, changed_paths: list[str]) -> dict[str, list[str]]:  # pylint: disable=too-many-locals
    """Scan all active todos and invalidate those with overlapping referenced paths.

    Reads state from todos.db (sync). When a todo's ``grounding.referenced_paths``
    overlaps with ``changed_paths``, invalidation routes through the typed
    :class:`StateWriter` + :class:`GroundingManager` boundary and the final
    commit uses ``commit_sync`` so malformed persisted state fails fast at load.
    """
    import json as _json  # pylint: disable=import-outside-toplevel

    from teleclaude.core.next_machine.state_mutation import (  # pylint: disable=import-outside-toplevel
        GroundingManager,
        StateWriter,
    )
    from teleclaude.core.todos_db import TodosDb  # pylint: disable=import-outside-toplevel

    invalidated: list[str] = []
    changed_set = set(changed_paths)

    project_root = resolve_main_repo_root(cwd)
    db = TodosDb(str(project_root / ".teleclaude" / "todos.db"))
    db.initialize_sync()
    conn = db._sync_conn()  # pylint: disable=protected-access

    try:
        rows = conn.execute(
            "SELECT id, slug, state FROM todo_state",  # guard: raw-sql
        ).fetchall()

        for row in rows:
            slug = row[1]
            raw_state = _json.loads(row[2]) if row[2] else {}
            writer = StateWriter(raw_state)  # fails fast on malformed persisted state
            referenced = list(writer.grounding.referenced_paths)
            overlap = [path for path in referenced if path in changed_set]
            if not overlap:
                continue

            GroundingManager(writer).invalidate(reason="files_changed", changed_paths=overlap)
            writer.state.current = PreparePhase.GROUNDING_CHECK.value
            writer.commit_sync(db, slug)

            _emit_prepare_event(
                "domain.software-development.prepare.grounding_invalidated",
                {"slug": slug, "reason": "files_changed", "changed_paths": overlap},
            )
            invalidated.append(slug)
    finally:
        conn.close()

    return {"invalidated": invalidated}


__all__ = [
    "_emit_prepare_event",
    "_has_test_spec_artifacts",
    "invalidate_stale_preparations",
]
