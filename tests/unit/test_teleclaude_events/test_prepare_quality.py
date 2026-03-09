"""Tests for PrepareQualityCartridge — scoring, idempotency, gap filling, resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from teleclaude_events.cartridges import (
    DeduplicationCartridge,
    NotificationProjectorCartridge,
    PrepareQualityCartridge,
)
from teleclaude_events.cartridges.prepare_quality import (
    _fill_plan_gaps,
    _fill_requirements_gaps,
    _is_slug_delivered_or_frozen,
    compute_dor_score,
    score_plan,
    score_requirements,
)
from teleclaude_events.catalog import EventCatalog, EventSchema, NotificationLifecycle
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope, EventLevel
from teleclaude_events.pipeline import Pipeline, PipelineContext

# ── Fixtures ──────────────────────────────────────────────────────────────────

_RICH_REQUIREMENTS = """\
# Requirements: My Feature

## Goal

Implement feature X to solve problem Y.

## Scope

### In scope
- Implement X
- Write tests

### Out of scope
- Unrelated feature Z

## Dependency

- `some-other-todo`

## Functional requirements

### FR1: Core behavior

- Must do A, B, C.

### FR2: Edge cases

- Handle empty input gracefully.

### FR3: Integration

- Integrate with existing pipeline.

## Acceptance criteria

1. All tests pass.
2. Feature is observable via CLI.

## Constraints

- Must not break existing API contracts.
"""

_WEAK_REQUIREMENTS = """\
# Requirements: Weak Feature

## Overview

We want to build something.
"""

_RICH_PLAN = """\
# Implementation Plan: My Feature

## Phase 1: Core

### Task 1.1: Implement main module

**File(s):** `teleclaude/core/feature.py` (new)

- [ ] Create the main class (FR1, FR2)
- [ ] Write unit tests in `tests/unit/test_feature.py`

**Verification:** Unit tests pass with `make test-unit`.

### Task 1.2: Wire into pipeline

**File(s):** `teleclaude/daemon.py`

- [ ] Import and add to pipeline (FR3)
- [ ] Verify startup logs show the new component

**Verification:** Daemon logs show component registered.

## Phase 2: Validation

### Task 2.1: Integration test

**File(s):** `tests/unit/test_pipeline.py`

- [ ] Add integration test covering all FRs

**Verification:** All tests pass with `make test`.

## Risks

1. Pipeline slowdown — mitigate: measure latency.

## Exit criteria

1. All tasks complete.
2. Tests passing.
"""

_WEAK_PLAN = """\
# Implementation Plan: Weak Feature

## Steps

- [ ] Do something
"""

# Artifacts that already have everything the gap filler can add (dep + constraints +
# verification + risks) but still score below 8 — gap filler produces no edits,
# triggering the needs_decision path.
_NEEDS_DECISION_REQUIREMENTS = """\
# Requirements: Needs Decision Feature

## Overview

We want something.

## Dependency

- some-dep

## Constraints

- Must be fast.
"""

_NEEDS_DECISION_PLAN = """\
# Implementation Plan: Needs Decision Feature

## Risks

None known.

**Verification:** Run tests.
"""


@pytest.fixture
async def db(tmp_path: Path) -> EventDB:  # type: ignore[misc]
    event_db = EventDB(db_path=tmp_path / "test_prepare_quality.db")
    await event_db.init()
    yield event_db  # type: ignore[misc]
    await event_db.close()


def _make_catalog() -> EventCatalog:
    catalog = EventCatalog()
    catalog.register(
        EventSchema(
            event_type="domain.software-development.planning.artifact_changed",
            description="Artifact changed",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug", "artifact"],
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["artifact"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.planning.todo_created",
            description="Todo created",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug"]),
        )
    )
    return catalog


def _make_planning_event(
    slug: str, event_type: str = "domain.software-development.planning.artifact_changed"
) -> EventEnvelope:
    return EventEnvelope(
        event=event_type,
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        payload={"slug": slug, "artifact": "requirements.md"},
    )


def _make_todo_dir(tmp_path: Path, slug: str, req_content: str = "", plan_content: str = "") -> Path:
    todo_dir = tmp_path / "todos" / slug
    todo_dir.mkdir(parents=True)
    if req_content:
        (todo_dir / "requirements.md").write_text(req_content)
    if plan_content:
        (todo_dir / "implementation-plan.md").write_text(plan_content)
    return todo_dir


# ── Scorer unit tests ─────────────────────────────────────────────────────────


def test_score_requirements_rich_content() -> None:
    result = score_requirements(_RICH_REQUIREMENTS)
    assert result["raw"] >= 6, f"Expected high score, got dims={result['dimensions']}"
    assert len(result["gaps"]) <= 2


def test_score_requirements_weak_content() -> None:
    result = score_requirements(_WEAK_REQUIREMENTS)
    assert result["raw"] <= 4, f"Expected low score, got dims={result['dimensions']}"
    assert len(result["gaps"]) >= 3


def test_score_plan_rich_content() -> None:
    result = score_plan(_RICH_PLAN, _RICH_REQUIREMENTS)
    assert result["raw"] >= 6, f"Expected high score, got dims={result['dimensions']}"
    assert len(result["gaps"]) <= 2


def test_score_plan_weak_content() -> None:
    result = score_plan(_WEAK_PLAN, _WEAK_REQUIREMENTS)
    assert result["raw"] <= 3, f"Expected low score, got dims={result['dimensions']}"
    assert len(result["gaps"]) >= 3


def test_compute_dor_score_pass_threshold() -> None:
    rich_req = score_requirements(_RICH_REQUIREMENTS)
    rich_plan = score_plan(_RICH_PLAN, _RICH_REQUIREMENTS)
    score, verdict = compute_dor_score(rich_req, rich_plan)
    assert score >= 8
    assert verdict == "pass"


def test_compute_dor_score_needs_work() -> None:
    weak_req = score_requirements(_WEAK_REQUIREMENTS)
    weak_plan = score_plan(_WEAK_PLAN, _WEAK_REQUIREMENTS)
    score, verdict = compute_dor_score(weak_req, weak_plan)
    assert score < 8
    assert verdict in ("needs_work", "needs_decision")


def test_compute_dor_score_minimum_is_1() -> None:
    empty_req = score_requirements("")
    empty_plan = score_plan("", "")
    score, _ = compute_dor_score(empty_req, empty_plan)
    assert score >= 1


def test_compute_dor_score_maximum_is_10() -> None:
    rich_req = score_requirements(_RICH_REQUIREMENTS)
    rich_plan = score_plan(_RICH_PLAN, _RICH_REQUIREMENTS)
    score, _ = compute_dor_score(rich_req, rich_plan)
    assert score <= 10


# ── Structural gap filler ─────────────────────────────────────────────────────


def test_fill_requirements_adds_dependency_section(tmp_path: Path) -> None:
    roadmap = tmp_path / "roadmap.yaml"
    roadmap.write_text(yaml.safe_dump([{"slug": "weak-feature", "deps": ["some-dep", "other-dep"]}]))
    gaps = ["requirements: missing Dependency / Prerequisites section"]
    new_content, edits = _fill_requirements_gaps(_WEAK_REQUIREMENTS, gaps, roadmap, "weak-feature")
    assert "Dependency" in new_content or "Prerequisites" in new_content
    assert len(edits) > 0


def test_fill_requirements_no_roadmap_skips(tmp_path: Path) -> None:
    roadmap = tmp_path / "roadmap.yaml"  # does not exist
    gaps = ["requirements: missing Dependency / Prerequisites section"]
    _new_content, edits = _fill_requirements_gaps(_WEAK_REQUIREMENTS, gaps, roadmap, "some-slug")
    assert len(edits) == 0


def test_fill_requirements_preserves_existing_prose(tmp_path: Path) -> None:
    roadmap = tmp_path / "roadmap.yaml"
    roadmap.write_text(yaml.safe_dump([{"slug": "dep"}]))
    original = _RICH_REQUIREMENTS
    gaps = ["something unrelated"]
    new_content, edits = _fill_requirements_gaps(original, gaps, roadmap, "some-slug")
    # Should not have changed since deps section already exists
    assert new_content == original
    assert len(edits) == 0


_PLAN_WITH_TASKS_NO_VERIFY = """\
# Implementation Plan: No-Verify Feature

## Phase 1: Core

### Task 1.1: Implement module

**File(s):** `teleclaude/core/thing.py`

- [ ] Create the main class (FR1)
- [ ] Write tests in `tests/unit/test_thing.py`

### Task 1.2: Wire into pipeline

**File(s):** `teleclaude/daemon.py`

- [ ] Import and add to pipeline (FR2)
"""


def test_fill_plan_adds_verification_placeholder() -> None:
    gaps = ["plan: missing **Verification:** steps in task sections"]
    new_content, edits = _fill_plan_gaps(_PLAN_WITH_TASKS_NO_VERIFY, gaps)
    assert "Verification" in new_content
    assert len(edits) > 0


def test_fill_plan_adds_risks_section() -> None:
    gaps = ["plan: missing Risks section"]
    new_content, edits = _fill_plan_gaps(_WEAK_PLAN, gaps)
    assert "Risks" in new_content
    assert len(edits) > 0


def test_fill_plan_preserves_existing_verification() -> None:
    gaps = ["plan: missing **Verification:** steps in task sections"]
    updated, _edits = _fill_plan_gaps(_RICH_PLAN, gaps)
    # Rich plan already has verification steps — count of Verification occurrences should be same
    original_count = _RICH_PLAN.count("**Verification:**")
    new_count = updated.count("**Verification:**")
    # May add at most 1 extra at the trailing task
    assert new_count >= original_count


# ── Delivered / frozen check ──────────────────────────────────────────────────


def test_is_slug_delivered(tmp_path: Path) -> None:
    delivered = tmp_path / "todos" / "delivered.yaml"
    delivered.parent.mkdir(parents=True)
    delivered.write_text(yaml.safe_dump([{"slug": "done-feature", "date": "2026-01-01"}]))
    assert _is_slug_delivered_or_frozen("done-feature", tmp_path) is True
    assert _is_slug_delivered_or_frozen("other-feature", tmp_path) is False


def test_is_slug_frozen_via_icebox_yaml(tmp_path: Path) -> None:
    icebox = tmp_path / "todos" / "_icebox" / "icebox.yaml"
    icebox.parent.mkdir(parents=True)
    icebox.write_text(yaml.safe_dump([{"slug": "frozen-feature"}]))
    assert _is_slug_delivered_or_frozen("frozen-feature", tmp_path) is True


def test_is_slug_frozen_via_new_icebox_yaml_path(tmp_path: Path) -> None:
    """Frozen slug must be detected when icebox.yaml is at todos/_icebox/icebox.yaml."""
    icebox = tmp_path / "todos" / "_icebox" / "icebox.yaml"
    icebox.parent.mkdir(parents=True)
    icebox.write_text(yaml.safe_dump([{"slug": "new-frozen-feature"}]))
    assert _is_slug_delivered_or_frozen("new-frozen-feature", tmp_path) is True
    assert _is_slug_delivered_or_frozen("other-feature", tmp_path) is False


# ── Cartridge pass-through ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_planning_event_passes_through(db: EventDB) -> None:
    catalog = EventCatalog()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    cartridge = PrepareQualityCartridge()

    env = EventEnvelope(
        event="system.daemon.restarted",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="system",
        payload={"computer": "local"},
    )
    result = await cartridge.process(env, context)
    assert result is env  # same object, unmodified


@pytest.mark.asyncio
async def test_planning_event_without_slug_passes_through(db: EventDB) -> None:
    catalog = EventCatalog()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    cartridge = PrepareQualityCartridge()

    env = EventEnvelope(
        event="domain.software-development.planning.artifact_changed",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        payload={},  # no slug
    )
    result = await cartridge.process(env, context)
    assert result is env


# ── Cartridge assessment ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cartridge_writes_dor_report(db: EventDB, tmp_path: Path) -> None:
    _make_todo_dir(tmp_path, "my-feature", req_content=_RICH_REQUIREMENTS, plan_content=_RICH_PLAN)

    catalog = _make_catalog()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    cartridge = PrepareQualityCartridge()
    event = _make_planning_event("my-feature")

    with patch("teleclaude_events.cartridges.prepare_quality._find_project_root", return_value=tmp_path):
        with patch("teleclaude_events.cartridges.prepare_quality._get_todo_commit", return_value="abc1234"):
            await cartridge.process(event, context)

    report_path = tmp_path / "todos" / "my-feature" / "dor-report.md"
    assert report_path.exists(), "dor-report.md should be written"
    report = report_path.read_text()
    assert "Score:" in report or "score" in report.lower()
    assert "my-feature" in report


@pytest.mark.asyncio
async def test_cartridge_writes_state_yaml(db: EventDB, tmp_path: Path) -> None:
    _make_todo_dir(tmp_path, "my-feature", req_content=_RICH_REQUIREMENTS, plan_content=_RICH_PLAN)

    catalog = _make_catalog()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    cartridge = PrepareQualityCartridge()
    event = _make_planning_event("my-feature")

    with patch("teleclaude_events.cartridges.prepare_quality._find_project_root", return_value=tmp_path):
        with patch("teleclaude_events.cartridges.prepare_quality._get_todo_commit", return_value="abc1234"):
            await cartridge.process(event, context)

    state_path = tmp_path / "todos" / "my-feature" / "state.yaml"
    assert state_path.exists(), "state.yaml should be written"
    state = yaml.safe_load(state_path.read_text())
    dor = state.get("dor", {})
    assert "score" in dor
    assert "status" in dor
    assert dor["schema_version"] == 1
    assert dor["assessed_commit"] == "abc1234"
    assert dor["status"] in ("pass", "needs_work", "needs_decision")


@pytest.mark.asyncio
async def test_cartridge_state_yaml_preserves_non_dor_keys(db: EventDB, tmp_path: Path) -> None:
    todo_dir = _make_todo_dir(tmp_path, "my-feature", req_content=_RICH_REQUIREMENTS, plan_content=_RICH_PLAN)
    existing_state = {"phase": "in_progress", "build": "pending", "some_custom_key": "preserved"}
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(existing_state))

    catalog = _make_catalog()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    cartridge = PrepareQualityCartridge()
    event = _make_planning_event("my-feature")

    with patch("teleclaude_events.cartridges.prepare_quality._find_project_root", return_value=tmp_path):
        with patch("teleclaude_events.cartridges.prepare_quality._get_todo_commit", return_value="abc1234"):
            await cartridge.process(event, context)

    state = yaml.safe_load((todo_dir / "state.yaml").read_text())
    assert state.get("phase") == "in_progress"
    assert state.get("some_custom_key") == "preserved"
    assert "dor" in state


@pytest.mark.asyncio
async def test_cartridge_idempotency_skips_same_commit(db: EventDB, tmp_path: Path) -> None:
    todo_dir = _make_todo_dir(tmp_path, "my-feature", req_content=_RICH_REQUIREMENTS, plan_content=_RICH_PLAN)
    # Pre-populate state with pass status at same commit
    state = {"dor": {"assessed_commit": "abc1234", "status": "pass", "score": 9, "schema_version": 1}}
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state))

    catalog = _make_catalog()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    cartridge = PrepareQualityCartridge()
    event = _make_planning_event("my-feature")

    with patch("teleclaude_events.cartridges.prepare_quality._find_project_root", return_value=tmp_path):
        with patch("teleclaude_events.cartridges.prepare_quality._get_todo_commit", return_value="abc1234"):
            await cartridge.process(event, context)

    # Report should NOT be written (skipped due to idempotency)
    report_path = todo_dir / "dor-report.md"
    assert not report_path.exists(), "No report should be written when idempotency skips processing"


@pytest.mark.asyncio
async def test_cartridge_reassesses_when_commit_changes(db: EventDB, tmp_path: Path) -> None:
    todo_dir = _make_todo_dir(tmp_path, "my-feature", req_content=_RICH_REQUIREMENTS, plan_content=_RICH_PLAN)
    # Pre-populate with OLD commit
    state = {"dor": {"assessed_commit": "old0000", "status": "pass", "score": 9, "schema_version": 1}}
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state))

    catalog = _make_catalog()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    cartridge = PrepareQualityCartridge()
    event = _make_planning_event("my-feature")

    with patch("teleclaude_events.cartridges.prepare_quality._find_project_root", return_value=tmp_path):
        with patch("teleclaude_events.cartridges.prepare_quality._get_todo_commit", return_value="new1234"):
            await cartridge.process(event, context)

    state_after = yaml.safe_load((todo_dir / "state.yaml").read_text())
    assert state_after["dor"]["assessed_commit"] == "new1234"


@pytest.mark.asyncio
async def test_cartridge_resolves_notification_on_pass(db: EventDB, tmp_path: Path) -> None:
    _make_todo_dir(tmp_path, "my-feature", req_content=_RICH_REQUIREMENTS, plan_content=_RICH_PLAN)

    catalog = _make_catalog()
    seed_schema = catalog.get("domain.software-development.planning.todo_created")
    assert seed_schema is not None

    seed_env = EventEnvelope(
        event="domain.software-development.planning.todo_created",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        payload={"slug": "my-feature"},
        idempotency_key="planning.todo_created:my-feature",
    )
    notif_id = await db.insert_notification(seed_env, seed_schema)

    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    cartridge = PrepareQualityCartridge()
    event = _make_planning_event("my-feature")

    with patch("teleclaude_events.cartridges.prepare_quality._find_project_root", return_value=tmp_path):
        with patch("teleclaude_events.cartridges.prepare_quality._get_todo_commit", return_value="abc1234"):
            await cartridge.process(event, context)

    row = await db.get_notification(notif_id)
    assert row is not None
    # For rich artifacts, verdict should be pass or needs_work → resolved
    assert row["agent_status"] == "resolved"


@pytest.mark.asyncio
async def test_cartridge_leaves_notification_claimed_on_needs_decision(db: EventDB, tmp_path: Path) -> None:
    # Use artifacts that already have everything the gap filler can add, so it
    # exhausts improvements and sets verdict=needs_decision (FR4).
    _make_todo_dir(
        tmp_path,
        "needs-decision-feature",
        req_content=_NEEDS_DECISION_REQUIREMENTS,
        plan_content=_NEEDS_DECISION_PLAN,
    )

    catalog = _make_catalog()
    seed_schema = catalog.get("domain.software-development.planning.todo_created")
    assert seed_schema is not None

    seed_env = EventEnvelope(
        event="domain.software-development.planning.todo_created",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        payload={"slug": "needs-decision-feature"},
        idempotency_key="planning.todo_created:needs-decision-feature",
    )
    notif_id = await db.insert_notification(seed_env, seed_schema)

    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    cartridge = PrepareQualityCartridge()
    event = _make_planning_event("needs-decision-feature")

    with patch("teleclaude_events.cartridges.prepare_quality._find_project_root", return_value=tmp_path):
        with patch("teleclaude_events.cartridges.prepare_quality._get_todo_commit", return_value="abc1234"):
            await cartridge.process(event, context)

    row = await db.get_notification(notif_id)
    assert row is not None
    # needs_decision: notification is claimed (work was done) but not resolved
    assert row["agent_status"] == "claimed"

    # DOR report should document the decision-needed state
    report_path = tmp_path / "todos" / "needs-decision-feature" / "dor-report.md"
    assert report_path.exists()
    report = report_path.read_text()
    assert "needs_decision" in report


@pytest.mark.asyncio
async def test_cartridge_returns_event_on_assess_exception(db: EventDB, tmp_path: Path) -> None:
    """_assess raising must not crash the pipeline — event is returned unchanged."""
    _make_todo_dir(tmp_path, "error-feature", req_content=_RICH_REQUIREMENTS, plan_content=_RICH_PLAN)

    catalog = _make_catalog()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    cartridge = PrepareQualityCartridge()
    event = _make_planning_event("error-feature")

    with patch("teleclaude_events.cartridges.prepare_quality._find_project_root", return_value=tmp_path):
        with patch("teleclaude_events.cartridges.prepare_quality._get_todo_commit", return_value="abc1234"):
            with patch.object(cartridge, "_assess", side_effect=RuntimeError("boom")):
                result = await cartridge.process(event, context)

    assert result is event  # pipeline must not drop the event on assessment failure


@pytest.mark.asyncio
async def test_cartridge_skips_delivered_slug(db: EventDB, tmp_path: Path) -> None:
    _make_todo_dir(tmp_path, "delivered-feat", req_content=_RICH_REQUIREMENTS, plan_content=_RICH_PLAN)
    delivered_path = tmp_path / "todos" / "delivered.yaml"
    delivered_path.write_text(yaml.safe_dump([{"slug": "delivered-feat", "date": "2026-01-01"}]))

    catalog = _make_catalog()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    cartridge = PrepareQualityCartridge()
    event = _make_planning_event("delivered-feat")

    with patch("teleclaude_events.cartridges.prepare_quality._find_project_root", return_value=tmp_path):
        with patch("teleclaude_events.cartridges.prepare_quality._get_todo_commit", return_value="abc1234"):
            await cartridge.process(event, context)

    # No report should be written for delivered slugs
    assert not (tmp_path / "todos" / "delivered-feat" / "dor-report.md").exists()


# ── Full pipeline integration ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_pipeline_with_prepare_quality(db: EventDB, tmp_path: Path) -> None:
    """Three-cartridge pipeline processes planning event without errors."""
    _make_todo_dir(tmp_path, "pipeline-feat", req_content=_RICH_REQUIREMENTS, plan_content=_RICH_PLAN)

    catalog = _make_catalog()
    push_callback = AsyncMock()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[push_callback])
    pipeline = Pipeline(
        [DeduplicationCartridge(), NotificationProjectorCartridge(), PrepareQualityCartridge()],
        context,
    )

    event = _make_planning_event("pipeline-feat")

    with patch("teleclaude_events.cartridges.prepare_quality._find_project_root", return_value=tmp_path):
        with patch("teleclaude_events.cartridges.prepare_quality._get_todo_commit", return_value="abc1234"):
            result = await pipeline.execute(event)

    assert result is not None, "Pipeline should not drop the event"
    report_path = tmp_path / "todos" / "pipeline-feat" / "dor-report.md"
    assert report_path.exists()


@pytest.mark.asyncio
async def test_full_pipeline_non_planning_event_unaffected(db: EventDB, tmp_path: Path) -> None:
    """Non-planning events pass through all three cartridges unchanged."""
    catalog = EventCatalog()
    catalog.register(
        EventSchema(
            event_type="system.test.event",
            description="test",
            default_level=EventLevel.WORKFLOW,
            domain="system",
            idempotency_fields=[],
        )
    )
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    pipeline = Pipeline(
        [DeduplicationCartridge(), NotificationProjectorCartridge(), PrepareQualityCartridge()],
        context,
    )

    event = EventEnvelope(
        event="system.test.event",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="system",
        payload={"info": "irrelevant"},
    )
    result = await pipeline.execute(event)
    assert result is not None


# ── Structural improvement rescores higher ────────────────────────────────────


def test_gap_filler_improves_score(tmp_path: Path) -> None:
    """After gap filling, rescore should produce same or higher score."""
    roadmap = tmp_path / "roadmap.yaml"
    roadmap.write_text(yaml.safe_dump([{"slug": "weak-feature", "deps": ["some-dep"]}]))
    gaps = ["requirements: missing Dependency / Prerequisites section"]
    new_req, edits = _fill_requirements_gaps(_WEAK_REQUIREMENTS, gaps, roadmap, "weak-feature")
    if edits:
        before = score_requirements(_WEAK_REQUIREMENTS)
        after = score_requirements(new_req)
        assert after["raw"] >= before["raw"]
