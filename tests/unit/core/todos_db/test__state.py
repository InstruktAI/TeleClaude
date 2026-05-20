"""Tests for TodosDbStateMixin — todo state persistence."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import cast

import pytest
from sqlmodel import select

from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db._models import TodoRoadmap
from teleclaude.core.todos_db._upcycle import LATEST_TODO_STATE_SCHEMA_VERSION

pytestmark = pytest.mark.asyncio

_RenameStateSlug = Callable[[str, str], Awaitable[bool]]
_SLUG = "phase-hook-slug"
_PRIOR_PHASE = "review_approved"
_NEW_PHASE = "finalize_ready"


def _rename_state_slug(todos_db: TodosDb) -> _RenameStateSlug:
    return cast(_RenameStateSlug, todos_db.rename_state_slug)


def _read_raw_state_json(todos_db: TodosDb, slug: str) -> dict:
    conn = todos_db._sync_conn()  # pylint: disable=protected-access
    try:
        row = conn.execute(
            "SELECT state FROM todo_state WHERE slug = ? LIMIT 1",  # guard: raw-sql
            (slug,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return json.loads(row[0])


def _overwrite_raw_state_json(todos_db: TodosDb, slug: str, state: dict) -> None:
    conn = todos_db._sync_conn()  # pylint: disable=protected-access
    try:
        conn.execute(
            "UPDATE todo_state SET state = ? WHERE slug = ?",  # guard: raw-sql
            (json.dumps(state), slug),
        )
        conn.commit()
    finally:
        conn.close()


async def test_read_state_returns_none_for_unknown_slug(todos_db: TodosDb) -> None:
    result = await todos_db.read_state("nonexistent")
    assert result is None


async def test_read_state_upcycles_v1_draft_purely_without_persisting(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("draft-slug")
    await todos_db.write_state(
        "draft-slug",
        {"kind": "draft", "schema_version": 1, "phase": "pending", "lifecycle_phase": "input_assessment"},
    )
    _overwrite_raw_state_json(
        todos_db,
        "draft-slug",
        {"kind": "draft", "schema_version": 1, "phase": "pending", "lifecycle_phase": "input_assessment"},
    )

    result = await todos_db.read_state("draft-slug")
    persisted = _read_raw_state_json(todos_db, "draft-slug")

    assert result is not None
    assert result["schema_version"] == LATEST_TODO_STATE_SCHEMA_VERSION
    assert result["lifecycle_phase"] == "draft"
    assert persisted["schema_version"] == 1
    assert persisted["lifecycle_phase"] == "input_assessment"


async def test_write_state_persists_latest_v3_and_drops_legacy_override_fields(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")

    await todos_db.write_state(
        "my-slug",
        {
            "schema_version": 1,
            "phase": "pending",
            "kind": "draft",
            "lifecycle_phase": "input_assessment",
            "prepare_phase": "requirements_review",
            "work_phase": "build_started",
        },
    )

    result = await todos_db.read_state("my-slug")
    persisted = _read_raw_state_json(todos_db, "my-slug")

    assert result is not None
    assert result["schema_version"] == LATEST_TODO_STATE_SCHEMA_VERSION
    assert result["lifecycle_phase"] == "draft"
    assert persisted["schema_version"] == LATEST_TODO_STATE_SCHEMA_VERSION
    assert persisted["lifecycle_phase"] == "draft"
    assert "prepare_phase" not in persisted
    assert "work_phase" not in persisted


async def test_write_state_accepts_legacy_current_payload_and_persists_latest_shape(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")

    await todos_db.write_state("my-slug", {"current": "prepared", "phase": "pending"})

    result = await todos_db.read_state("my-slug")
    persisted = _read_raw_state_json(todos_db, "my-slug")

    assert result is not None
    assert result["schema_version"] == LATEST_TODO_STATE_SCHEMA_VERSION
    assert result["lifecycle_phase"] == "prepared"
    assert persisted["schema_version"] == LATEST_TODO_STATE_SCHEMA_VERSION
    assert persisted["lifecycle_phase"] == "prepared"
    assert "current" not in persisted


async def test_write_state_updates_existing_row(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"lifecycle_phase": "prd_drafting"})
    await todos_db.write_state("my-slug", {"lifecycle_phase": "prepared"})

    result = await todos_db.read_state("my-slug")
    assert result is not None
    assert result["lifecycle_phase"] == "prepared"
    assert result["schema_version"] == LATEST_TODO_STATE_SCHEMA_VERSION


async def test_write_state_fires_phase_transition_after_owned_commit(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap(_SLUG)
    await todos_db.write_state(_SLUG, {"lifecycle_phase": _PRIOR_PHASE})
    calls: list[tuple[str, str, str, Mapping[str, object]]] = []
    todos_db._on_phase_transition = lambda slug, prior, new, state: calls.append((slug, prior, new, dict(state)))

    await todos_db.write_state(_SLUG, {"lifecycle_phase": _NEW_PHASE})

    assert len(calls) == 1
    slug, prior_phase, new_phase, payload = calls[0]
    assert slug == _SLUG
    assert prior_phase == _PRIOR_PHASE
    assert new_phase == _NEW_PHASE
    assert payload["lifecycle_phase"] == _NEW_PHASE


async def test_write_state_skips_phase_transition_when_phase_is_unchanged(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap(_SLUG)
    await todos_db.write_state(_SLUG, {"lifecycle_phase": _NEW_PHASE})
    calls: list[tuple[str, str, str, Mapping[str, object]]] = []
    todos_db._on_phase_transition = lambda slug, prior, new, state: calls.append((slug, prior, new, dict(state)))

    await todos_db.write_state(_SLUG, {"lifecycle_phase": _NEW_PHASE})

    assert calls == []


async def test_write_state_skips_phase_transition_for_caller_owned_session(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap(_SLUG)
    await todos_db.write_state(_SLUG, {"lifecycle_phase": _PRIOR_PHASE})
    calls: list[tuple[str, str, str, Mapping[str, object]]] = []
    todos_db._on_phase_transition = lambda slug, prior, new, state: calls.append((slug, prior, new, dict(state)))

    async with todos_db._session() as session:
        await todos_db.write_state(_SLUG, {"lifecycle_phase": _NEW_PHASE}, session=session)
        await session.commit()

    assert calls == []


async def test_write_state_sync_fires_phase_transition_after_owned_commit(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap(_SLUG)
    await todos_db.write_state(_SLUG, {"lifecycle_phase": _PRIOR_PHASE})
    calls: list[tuple[str, str, str, Mapping[str, object]]] = []
    todos_db._on_phase_transition = lambda slug, prior, new, state: calls.append((slug, prior, new, dict(state)))

    todos_db.write_state_sync(_SLUG, {"lifecycle_phase": _NEW_PHASE})

    assert len(calls) == 1
    slug, prior_phase, new_phase, payload = calls[0]
    assert slug == _SLUG
    assert prior_phase == _PRIOR_PHASE
    assert new_phase == _NEW_PHASE
    assert payload["lifecycle_phase"] == _NEW_PHASE


async def test_concurrent_finalize_ready_writes_emit_phase_transition_at_least_once(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap(_SLUG)
    await todos_db.write_state(_SLUG, {"lifecycle_phase": _PRIOR_PHASE})
    calls: list[tuple[str, str, str, Mapping[str, object]]] = []
    todos_db._on_phase_transition = lambda slug, prior, new, state: calls.append((slug, prior, new, dict(state)))

    await asyncio.gather(
        todos_db.write_state(_SLUG, {"lifecycle_phase": _NEW_PHASE}),
        todos_db.write_state(_SLUG, {"lifecycle_phase": _NEW_PHASE}),
    )

    assert len(calls) >= 1


async def test_delete_state_removes_row(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"lifecycle_phase": "prd_drafting"})
    await todos_db.delete_state("my-slug")
    assert await todos_db.read_state("my-slug") is None


async def test_list_slugs_returns_all_stored(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("alpha")
    await todos_db.add_to_roadmap("beta")
    await todos_db.write_state("alpha", {"lifecycle_phase": "prd_drafting"})
    await todos_db.write_state("beta", {"lifecycle_phase": "prepared"})
    slugs = await todos_db.list_slugs()
    assert set(slugs) == {"alpha", "beta"}


async def test_list_slugs_empty_when_no_state(todos_db: TodosDb) -> None:
    slugs = await todos_db.list_slugs()
    assert slugs == []


async def test_is_bug_todo_returns_true_for_bug_kind(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("bug-slug")
    await todos_db.write_state("bug-slug", {"kind": "bug", "lifecycle_phase": "prd_drafting"})
    assert await todos_db.is_bug_todo("bug-slug") is True


async def test_is_bug_todo_returns_false_for_regular_todo(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("todo-slug")
    await todos_db.write_state("todo-slug", {"kind": "feature", "lifecycle_phase": "prd_drafting"})
    assert await todos_db.is_bug_todo("todo-slug") is False


async def test_has_pending_deferrals_false_when_no_artifact(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"lifecycle_phase": "prd_drafting"})
    assert await todos_db.has_pending_deferrals("my-slug") is False


async def test_has_pending_deferrals_true_when_artifact_exists(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"lifecycle_phase": "prd_drafting", "deferrals_processed": False})
    await todos_db.write_artifact("my-slug", "deferrals", "some deferrals")
    assert await todos_db.has_pending_deferrals("my-slug") is True


async def test_has_pending_deferrals_false_when_processed(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"lifecycle_phase": "prd_drafting", "deferrals_processed": True})
    await todos_db.write_artifact("my-slug", "deferrals", "some deferrals")
    assert await todos_db.has_pending_deferrals("my-slug") is False


async def test_write_state_raises_when_no_roadmap_entry(todos_db: TodosDb) -> None:
    """write_state fails fast when slug has no active/icebox roadmap entry."""
    with pytest.raises(ValueError, match="no active/icebox roadmap entry"):
        await todos_db.write_state("orphan", {"lifecycle_phase": "prd_drafting"})


async def test_write_state_raises_when_slug_is_delivered(todos_db: TodosDb) -> None:
    """write_state fails fast for delivered slugs — deliver_sync owns that path."""
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"lifecycle_phase": "finalize_ready"})
    await todos_db.deliver("my-slug", commit="abc123")
    with pytest.raises(ValueError, match="no active/icebox roadmap entry"):
        await todos_db.write_state("my-slug", {"lifecycle_phase": "prd_drafting"})


async def test_read_state_returns_none_for_delivered_slug(todos_db: TodosDb) -> None:
    """read_state returns None for delivered slugs — use read_state_delivered instead."""
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"lifecycle_phase": "finalize_ready"})
    await todos_db.deliver("my-slug", commit="abc123")
    assert await todos_db.read_state("my-slug") is None


async def test_read_state_delivered_returns_state_for_delivered_slug(todos_db: TodosDb) -> None:
    """read_state_delivered reads state for delivered slugs via roadmap ID join."""
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"lifecycle_phase": "finalize_ready"})
    await todos_db.deliver("my-slug", commit="abc123")
    result = await todos_db.read_state_delivered("my-slug")
    assert result is not None
    assert result["lifecycle_phase"] == "finalize_ready"


async def test_read_state_delivered_returns_none_for_active_slug(todos_db: TodosDb) -> None:
    """read_state_delivered returns None when the slug is not delivered."""
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"lifecycle_phase": "prd_drafting"})
    assert await todos_db.read_state_delivered("my-slug") is None


async def test_deliver_stamps_integration_phase_delivered(todos_db: TodosDb) -> None:
    """deliver_sync sets integration_phase='delivered' in the state JSON."""
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"lifecycle_phase": "finalize_ready", "integration_phase": "started"})
    todos_db.deliver_sync("my-slug", commit="abc123")
    result = await todos_db.read_state_delivered("my-slug")
    assert result is not None
    assert result["integration_phase"] == "delivered"


async def test_deliver_stamps_integration_phase_even_when_stale(todos_db: TodosDb) -> None:
    """deliver_sync overwrites any stale integration_phase with 'delivered'."""
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state(
        "my-slug", {"lifecycle_phase": "finalize_ready", "integration_phase": "delivery_bookkeeping"}
    )
    todos_db.deliver_sync("my-slug", commit="abc123")
    result = await todos_db.read_state_delivered("my-slug")
    assert result is not None
    assert result["integration_phase"] == "delivered"


async def test_async_deliver_stamps_integration_phase_delivered(todos_db: TodosDb) -> None:
    """Async deliver() sets integration_phase='delivered' in the state JSON."""
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"lifecycle_phase": "finalize_ready", "integration_phase": "started"})
    await todos_db.deliver("my-slug", commit="abc123")
    result = await todos_db.read_state_delivered("my-slug")
    assert result is not None
    assert result["integration_phase"] == "delivered"


def _mark_removed(todos_db: TodosDb, slug: str) -> None:
    """Force a slug's live row into the persisted removed state (state row retained)."""
    with todos_db._sync_session() as session:
        entry = session.exec(
            select(TodoRoadmap).where(TodoRoadmap.slug == slug).where(TodoRoadmap.status != "removed").limit(1)
        ).one()
        entry.prev_status = entry.status
        entry.status = "removed"
        entry.removed_at = "2026-05-19T00:00:00+00:00"
        session.add(entry)
        session.commit()


async def test_read_state_excludes_removed(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("doomed")
    await todos_db.write_state("doomed", {"lifecycle_phase": "prepared", "kind": "todo"})
    _mark_removed(todos_db, "doomed")

    assert await todos_db.read_state("doomed") is None
    assert todos_db.read_state_sync("doomed") is None


async def test_write_state_rejects_removed(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("doomed")
    await todos_db.write_state("doomed", {"lifecycle_phase": "prepared", "kind": "todo"})
    _mark_removed(todos_db, "doomed")

    with pytest.raises(ValueError):
        await todos_db.write_state("doomed", {"lifecycle_phase": "build", "kind": "todo"})
    with pytest.raises(ValueError):
        todos_db.write_state_sync("doomed", {"lifecycle_phase": "build", "kind": "todo"})


async def test_list_slugs_excludes_removed(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("kept")
    await todos_db.write_state("kept", {"lifecycle_phase": "prepared", "kind": "todo"})
    await todos_db.add_to_roadmap("gone")
    await todos_db.write_state("gone", {"lifecycle_phase": "prepared", "kind": "todo"})
    _mark_removed(todos_db, "gone")

    assert await todos_db.list_slugs() == ["kept"]


async def test_rename_state_slug_rekeys_live_row_and_typed_breakdown_refs_only(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("old-slug")
    await todos_db.write_state(
        "old-slug",
        {
            "kind": "feature",
            "lifecycle_phase": "prepared",
            "breakdown": {"assessed": True, "todos": ["old-slug", "sibling"]},
            "events": [
                {
                    "at": "2026-05-19T00:00:00+00:00",
                    "actor": "tester",
                    "kind": "note",
                    "details": {"text": "old-slug remains prose"},
                }
            ],
        },
    )

    renamed = await _rename_state_slug(todos_db)("old-slug", "new-slug")
    roadmap_renamed = await todos_db.rename_roadmap_slug("old-slug", "new-slug")

    assert renamed is True
    assert roadmap_renamed is True
    assert await todos_db.read_state("old-slug") is None
    state = await todos_db.read_state("new-slug")
    assert state is not None
    assert state["breakdown"]["todos"] == ["new-slug", "sibling"]  # type: ignore[index]
    assert state["events"][0]["details"]["text"] == "old-slug remains prose"  # type: ignore[index]
    assert await todos_db.list_slugs() == ["new-slug"]
