"""Tests for the assemble_show_payload draft fast-path."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import cast

import pytest
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

from teleclaude.constants import ARTIFACT_IMPLEMENTATION_PLAN, ARTIFACT_PRD, ARTIFACT_QUALITY_CHECKLIST
from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db._show import _EVENTS_INLINE_LIMIT, assemble_show_payload
from teleclaude.types.todos import DriftReviewedStamp, Event, TodoState

pytestmark = pytest.mark.asyncio

_SLUG = "show-rich"
_ARTIFACT_BODY = "artifact body"
_TIMESTAMP_PATHS = {
    "artifact_state.*.produced_at": (str,),
    "roadmap.created_at": (str,),
    "roadmap.updated_at": (str,),
}


def _timestamp_replacer(_data: object, _path: object) -> str:
    return "TIMESTAMP"


async def _write_state(todos_db: TodosDb, slug: str, state: TodoState) -> None:
    await todos_db.write_state(slug, state.model_dump(exclude_none=True))


async def test_show_payload_draft_todo_reports_draft_stage(todos_db: TodosDb) -> None:
    """Draft todos should report stage='draft' and current.phase='draft' from canonical lifecycle state."""
    await todos_db.add_to_roadmap("draft-item")
    await todos_db.write_state("draft-item", {"kind": "draft", "schema_version": 1, "phase": "pending"})
    await todos_db.write_artifact("draft-item", "input", "some idea")

    payload = await assemble_show_payload(todos_db, "draft-item")

    assert payload is not None
    assert payload["stage"] == "draft"
    assert payload["current"]["phase"] == "draft"


async def test_show_payload_pending_draft_todo_reports_pending_current_state(todos_db: TodosDb) -> None:
    """A draft todo with no active worker should keep current.state aligned to the item phase."""
    state = TodoState.defaults()
    state.kind = "feature"
    await todos_db.add_to_roadmap("feature-draft")
    await todos_db.write_state("feature-draft", state.model_dump(exclude_none=True))

    payload = await assemble_show_payload(todos_db, "feature-draft")

    assert payload is not None
    assert payload["current"]["state"] == state.phase


async def test_show_payload_omits_complete_holder_from_blocked_by(todos_db: TodosDb) -> None:
    """A holder dependency stops blocking once its children have delivered."""
    await todos_db.add_to_roadmap("holder")
    await todos_db.add_to_roadmap("child-a", group_slug="holder")
    await todos_db.write_state("child-a", {"schema_version": 3, "lifecycle_phase": "finalize_ready"})
    await todos_db.deliver("child-a")
    await todos_db.add_to_roadmap("ready-after-holder")
    await todos_db.write_state("ready-after-holder", {"schema_version": 3, "lifecycle_phase": "prepared"})
    await todos_db.set_deps("ready-after-holder", after=["holder"])

    payload = await assemble_show_payload(todos_db, "ready-after-holder")

    assert payload is not None
    assert "blocked_by" not in payload


async def test_show_payload_default_omits_artifact_bodies(todos_db: TodosDb, snapshot: SnapshotAssertion) -> None:
    await todos_db.add_to_roadmap(_SLUG)
    await _write_state(todos_db, _SLUG, TodoState.defaults())
    await todos_db.write_artifact(_SLUG, ARTIFACT_PRD, _ARTIFACT_BODY)

    payload = await assemble_show_payload(todos_db, _SLUG)

    assert payload is not None
    assert payload == snapshot(matcher=path_type(_TIMESTAMP_PATHS, regex=True, replacer=_timestamp_replacer))


async def test_show_payload_artifacts_is_list_in_default(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap(_SLUG)
    await _write_state(todos_db, _SLUG, TodoState.defaults())
    await todos_db.write_artifact(_SLUG, ARTIFACT_PRD, _ARTIFACT_BODY)

    payload = await assemble_show_payload(todos_db, _SLUG)

    assert payload is not None
    assert isinstance(payload["artifacts"], list)


async def test_show_payload_include_artifact_content_restores_bodies(
    todos_db: TodosDb, snapshot: SnapshotAssertion
) -> None:
    await todos_db.add_to_roadmap(_SLUG)
    await _write_state(todos_db, _SLUG, TodoState.defaults())
    await todos_db.write_artifact(_SLUG, ARTIFACT_PRD, _ARTIFACT_BODY)

    payload = await assemble_show_payload(todos_db, _SLUG, include_artifact_content=True)

    assert payload is not None
    assert payload == snapshot(matcher=path_type(_TIMESTAMP_PATHS, regex=True, replacer=_timestamp_replacer))


async def test_show_payload_exposes_approvals_block(todos_db: TodosDb) -> None:
    state = TodoState.defaults()
    state.approvals.prd_approved.approved = True
    await todos_db.add_to_roadmap(_SLUG)
    await _write_state(todos_db, _SLUG, state)

    payload = await assemble_show_payload(todos_db, _SLUG)

    assert payload is not None
    prd_approved = payload["approvals"]["prd_approved"]
    assert isinstance(prd_approved, dict)
    assert prd_approved["approved"] is True


async def test_show_payload_exposes_drift_stamps(todos_db: TodosDb) -> None:
    state = TodoState.defaults()
    state.approvals.drift_reviewed[ARTIFACT_PRD] = DriftReviewedStamp(
        verdict="cosmetic",
        reason="comments only",
    )
    await todos_db.add_to_roadmap(_SLUG)
    await _write_state(todos_db, _SLUG, state)

    payload = await assemble_show_payload(todos_db, _SLUG)

    assert payload is not None
    drift = payload["drift"][ARTIFACT_PRD]
    approval_drift = payload["approvals"]["drift_reviewed"]
    assert isinstance(drift, dict)
    assert isinstance(approval_drift, dict)
    assert drift["verdict"] == "cosmetic"
    approval_drift_stamps = cast(dict[str, dict[str, str]], approval_drift)
    assert approval_drift_stamps[ARTIFACT_PRD]["reason"] == "comments only"


async def test_show_payload_exposes_reviews_block(todos_db: TodosDb) -> None:
    state = TodoState.defaults()
    state.plan_review.verdict = "approve"
    state.plan_review.cleared_by_substantive_drift = True
    await todos_db.add_to_roadmap(_SLUG)
    await _write_state(todos_db, _SLUG, state)

    payload = await assemble_show_payload(todos_db, _SLUG)

    assert payload is not None
    plan_review = payload["reviews"]["plan_review"]
    assert isinstance(plan_review, dict)
    assert plan_review["verdict"] == "approve"
    assert plan_review["cleared_by_substantive_drift"] is True


async def test_show_payload_exposes_work_block(todos_db: TodosDb) -> None:
    state = TodoState.defaults()
    state.build_start_base_sha = "abc123"
    await todos_db.add_to_roadmap(_SLUG)
    await _write_state(todos_db, _SLUG, state)

    payload = await assemble_show_payload(todos_db, _SLUG)

    assert payload is not None
    assert payload["work"]["build_start_base_sha"] == "abc123"


async def test_show_payload_exposes_artifact_state_block(todos_db: TodosDb) -> None:
    state = TodoState.defaults()
    state.artifacts.prd.digest = "prd-digest"
    state.artifacts.prd.produced_at = "2026-05-22T00:00:00+00:00"
    state.artifacts.implementation_plan.digest = "plan-digest"
    state.artifacts.implementation_plan.produced_at = "2026-05-22T00:00:01+00:00"
    await todos_db.add_to_roadmap(_SLUG)
    await _write_state(todos_db, _SLUG, state)
    await todos_db.write_artifact(_SLUG, ARTIFACT_PRD, _ARTIFACT_BODY)
    await todos_db.write_artifact(_SLUG, ARTIFACT_IMPLEMENTATION_PLAN, "plan body")
    await todos_db.write_artifact(_SLUG, ARTIFACT_QUALITY_CHECKLIST, "checklist body")

    payload = await assemble_show_payload(todos_db, _SLUG)

    assert payload is not None
    assert payload["artifact_state"][ARTIFACT_PRD]["digest"] == "prd-digest"
    assert payload["artifact_state"][ARTIFACT_PRD]["produced_at"]
    assert payload["artifact_state"][ARTIFACT_IMPLEMENTATION_PLAN]["digest"] == "plan-digest"
    checklist_state = payload["artifact_state"][ARTIFACT_QUALITY_CHECKLIST]
    assert checklist_state["digest"] == hashlib.sha256(b"checklist body").hexdigest()
    assert checklist_state["async_provenance_complete"] is False
    assert isinstance(checklist_state["produced_at"], str)
    datetime.fromisoformat(checklist_state["produced_at"])


async def test_show_payload_exposes_roadmap_block(todos_db: TodosDb) -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = "prepared"
    await todos_db.add_to_roadmap(_SLUG, description="desc")
    await _write_state(todos_db, _SLUG, state)
    await todos_db.stamp_ready_since_if_null(_SLUG, "2026-05-22T00:00:00+00:00")

    payload = await assemble_show_payload(todos_db, _SLUG)

    assert payload is not None
    assert payload["roadmap"]["status"] == "active"
    assert payload["roadmap"]["description"] == "desc"
    assert payload["roadmap"]["created_at"]
    assert payload["roadmap"]["updated_at"]
    assert payload["roadmap"]["ready_since"]
    assert "band" not in payload["roadmap"]


async def test_show_payload_exposes_state_block(todos_db: TodosDb) -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = "prepared"
    state.deferrals_processed = True
    await todos_db.add_to_roadmap(_SLUG)
    await _write_state(todos_db, _SLUG, state)

    payload = await assemble_show_payload(todos_db, _SLUG)

    assert payload is not None
    assert payload["state"]["schema_version"] == 4
    assert payload["state"]["kind"] == "todo"
    assert payload["state"]["lifecycle_phase"] == "prepared"
    assert payload["state"]["deferrals_processed"] is True


async def test_show_payload_exposes_audit_block(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap(_SLUG)
    await _write_state(todos_db, _SLUG, TodoState.defaults())

    payload = await assemble_show_payload(todos_db, _SLUG)

    assert payload is not None
    assert "prd_drafting" in payload["audit"]


async def test_show_payload_events_bounded(todos_db: TodosDb) -> None:
    state = TodoState.defaults()
    state.events = [
        Event(at=f"2026-05-22T00:00:{index:02d}+00:00", actor="tester", kind="event")
        for index in range(_EVENTS_INLINE_LIMIT + 1)
    ]
    await todos_db.add_to_roadmap(_SLUG)
    await _write_state(todos_db, _SLUG, state)

    payload = await assemble_show_payload(todos_db, _SLUG)

    assert payload is not None
    events = payload["events"]
    assert isinstance(events, dict)
    assert events["count"] == _EVENTS_INLINE_LIMIT + 1
    tail = events["tail"]
    assert isinstance(tail, list)
    assert len(tail) == _EVENTS_INLINE_LIMIT


async def test_show_payload_events_inline_under_limit(todos_db: TodosDb) -> None:
    state = TodoState.defaults()
    state.events = [Event(at="2026-05-22T00:00:00+00:00", actor="tester", kind="event")]
    await todos_db.add_to_roadmap(_SLUG)
    await _write_state(todos_db, _SLUG, state)

    payload = await assemble_show_payload(todos_db, _SLUG)

    assert payload is not None
    assert isinstance(payload["events"], list)
    assert payload["events"][0]["kind"] == "event"


async def test_show_payload_next_commands_present(todos_db: TodosDb, snapshot: SnapshotAssertion) -> None:
    await todos_db.add_to_roadmap(_SLUG)
    await _write_state(todos_db, _SLUG, TodoState.defaults())

    payload = await assemble_show_payload(todos_db, _SLUG)

    assert payload is not None
    assert payload["next_commands"] == snapshot


async def test_show_payload_backward_compatible_top_level_fields(todos_db: TodosDb) -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = "prepared"
    await todos_db.add_to_roadmap(_SLUG, description="desc")
    await _write_state(todos_db, _SLUG, state)

    payload = await assemble_show_payload(todos_db, _SLUG)

    assert payload is not None
    assert payload["slug"] == _SLUG
    assert payload["stage"] == "work"
    assert payload["description"] == "desc"
    assert payload["current"]["phase"] == "prepared"
    assert payload["previous"] == "plan_review"
    assert payload["next"] == "build"
