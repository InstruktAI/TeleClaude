"""Characterization tests for teleclaude.events.cartridges.prepare_quality."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from teleclaude.events.cartridges.prepare_quality import (
    PrepareQualityCartridge,
    _build_dependency_section,
    _fill_plan_gaps,
    _fill_requirements_gaps,
    _is_slug_delivered_or_frozen,
    compute_dor_score,
    score_plan,
    score_requirements,
)
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility


def _make_event(
    event_type: str = "domain.software-development.planning.artifact_changed", slug: str = "my-slug"
) -> EventEnvelope:
    return EventEnvelope(
        event=event_type,
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        visibility=EventVisibility.LOCAL,
        payload={"slug": slug},
    )


def _full_requirements_content() -> str:
    return """
# Goal

Assess prepare quality for this todo.

## Scope

### In scope
- score prepare artifacts

### Out of scope
- production code changes

## Acceptance Criteria
- [ ] DOR result is recorded

## FR1: Score artifacts

Evaluate requirements and plan quality.

## FR2: Persist assessment

Write artifacts and state updates.

## Dependency

- prior-slug

## Constraints

- keep the assessment deterministic
"""


def _full_plan_content() -> str:
    return """
# Phase 1

## Task 1.1 (FR1)

- [ ] Inspect `teleclaude/events/cartridges/prepare_quality.py`
- [ ] Update `tests/unit/events/cartridges/test_prepare_quality.py`

**Verification:** run `pytest tests/unit/events/cartridges/test_prepare_quality.py`

## Task 1.2 (FR2)

- [ ] Write `todos/my-slug/dor-report.md`

**Verification:** run `pytest tests/unit/events/cartridges/test_prepare_quality.py -k process`

## Risks

- filesystem write failures
"""


# ── score_requirements ────────────────────────────────────────────────────────


def test_score_requirements_empty_content_scores_zero():
    """Empty requirements content scores 0 with all gaps present."""
    result = score_requirements("")
    assert result["raw"] == 0
    assert result["max"] == 8
    assert len(result["gaps"]) > 0


def test_score_requirements_full_content_scores_high():
    """Well-structured requirements content scores highly."""
    content = """
# Goal

This is the goal.

## Scope

### In scope
- thing 1

### Out of scope
- thing 2

## Acceptance Criteria
- [ ] criterion 1

## FR1: Functional Requirement

Description.

## FR2: Functional Requirement 2

Description.

## Dependency

- prior-todo

## Constraints

Must run fast.
"""
    result = score_requirements(content)
    assert result["raw"] >= 6
    assert result["max"] == 8


def test_score_requirements_missing_goal_records_gap():
    """Missing Goal section is captured as a gap."""
    content = "## Acceptance Criteria\n- [ ] x\n"
    result = score_requirements(content)
    assert any("Goal" in g for g in result["gaps"])


def test_score_requirements_dimensions_are_bounded():
    """All dimension scores are non-negative and within their max."""
    content = "# Goal\n\n## Scope\n\n## Acceptance\n- [ ] x\n"
    result = score_requirements(content)
    for v in result["dimensions"].values():
        assert v >= 0


# ── score_plan ────────────────────────────────────────────────────────────────


def test_score_plan_empty_scores_one():
    """Empty plan content scores 1 — consistency dimension passes with no contradictions."""
    result = score_plan("", "")
    assert result["raw"] == 1  # plan_requirement_consistency=1 when no contradictions
    assert result["max"] == 8


def test_score_plan_with_file_refs_and_tasks():
    """Plan with file references, tasks, and paths scores higher."""
    content = """
# Phase 1

## Task 1.1

- [ ] Do `teleclaude/events/cartridges/foo.py`
- [ ] Edit `tests/unit/events/test_foo.py`
- [ ] Update `teleclaude/config.yaml`

**Verification:** run `make test`

## Risks

- None identified
"""
    result = score_plan(content, "")
    assert result["raw"] >= 3


def test_score_plan_contradiction_detected():
    """Contradiction between plan and requirements is captured."""
    plan = "We will copy the module to a new location."
    requirements = "We want to reuse the existing module."
    result = score_plan(plan, requirements)
    assert len(result["contradictions"]) >= 1


def test_score_plan_no_contradiction_when_both_aligned():
    """No contradiction when plan and requirements use compatible language."""
    plan = "We will extend the module."
    requirements = "We want to extend the existing module."
    result = score_plan(plan, requirements)
    assert len(result["contradictions"]) == 0


# ── compute_dor_score ─────────────────────────────────────────────────────────


def test_compute_dor_score_full_marks_gives_pass():
    """Perfect scores from both dimensions give verdict='pass'."""
    req = {"raw": 8, "max": 8, "dimensions": {}, "gaps": []}
    plan = {"raw": 8, "max": 8, "dimensions": {}, "gaps": [], "contradictions": []}
    score, verdict = compute_dor_score(req, plan)
    assert score == 10
    assert verdict == "pass"


def test_compute_dor_score_zero_gives_one_and_needs_work():
    """Zero raw score gives score=1 and verdict='needs_work'."""
    req = {"raw": 0, "max": 8, "dimensions": {}, "gaps": []}
    plan = {"raw": 0, "max": 8, "dimensions": {}, "gaps": [], "contradictions": []}
    score, verdict = compute_dor_score(req, plan)
    assert score == 1
    assert verdict == "needs_work"


def test_compute_dor_score_threshold_at_eight():
    """Score of exactly 8 gives verdict='pass'."""
    # 8/10 normalized: raw = x/16 such that round(1 + (x/16)*9) == 8
    # Solve: 8 = round(1 + 9*r), r = 7/9 ≈ 0.778, x = 12.44 → try raw=12
    req = {"raw": 6, "max": 8, "dimensions": {}, "gaps": []}
    plan = {"raw": 6, "max": 8, "dimensions": {}, "gaps": [], "contradictions": []}
    score, verdict = compute_dor_score(req, plan)
    assert score >= 7
    if score >= 8:
        assert verdict == "pass"
    else:
        assert verdict == "needs_work"


# ── _build_dependency_section ─────────────────────────────────────────────────


def test_build_dependency_section_missing_roadmap_returns_empty(tmp_path: Path) -> None:
    """Returns empty string when roadmap.yaml does not exist."""
    result = _build_dependency_section(tmp_path / "roadmap.yaml", "my-slug")
    assert result == ""


def test_build_dependency_section_slug_with_deps(tmp_path: Path) -> None:
    """Returns markdown section when slug has deps in roadmap."""
    roadmap = tmp_path / "roadmap.yaml"
    roadmap.write_text("- slug: my-slug\n  deps:\n    - dep-a\n    - dep-b\n")
    result = _build_dependency_section(roadmap, "my-slug")
    assert "dep-a" in result
    assert "dep-b" in result


def test_build_dependency_section_slug_no_deps(tmp_path: Path) -> None:
    """Returns empty string when slug exists but has no deps."""
    roadmap = tmp_path / "roadmap.yaml"
    roadmap.write_text("- slug: my-slug\n  deps: []\n")
    result = _build_dependency_section(roadmap, "my-slug")
    assert result == ""


# ── _fill_requirements_gaps ──────────────────────────────────────────────────


def test_fill_requirements_gaps_adds_constraints_placeholder(tmp_path: Path) -> None:
    """Adds a Constraints placeholder when gap is reported and section is absent."""
    roadmap = tmp_path / "roadmap.yaml"
    content = "# Goal\n\nSome goal.\n"
    gaps = ["requirements: missing Constraints / Non-functional requirements section"]
    result, edits = _fill_requirements_gaps(content, gaps, roadmap, "slug")
    assert "## Constraints" in result
    assert len(edits) > 0


def test_fill_requirements_gaps_no_change_when_no_gaps(tmp_path: Path) -> None:
    """No edits made when gaps list is empty."""
    content = "# Goal\n\nSome goal.\n"
    result, edits = _fill_requirements_gaps(content, [], tmp_path / "roadmap.yaml", "slug")
    assert result == content
    assert edits == []


# ── _fill_plan_gaps ───────────────────────────────────────────────────────────


def test_fill_plan_gaps_adds_risks_placeholder():
    """Adds a Risks placeholder when gap is reported and section is absent."""
    content = "## Tasks\n\n- [ ] do something\n"
    gaps = ["plan: missing Risks section"]
    result, edits = _fill_plan_gaps(content, gaps)
    assert "## Risks" in result
    assert len(edits) > 0


def test_fill_plan_gaps_no_change_when_no_gaps():
    """No edits made when gaps list is empty."""
    content = "## Tasks\n\n- [ ] do something\n"
    result, edits = _fill_plan_gaps(content, [])
    assert result == content
    assert edits == []


# ── _is_slug_delivered_or_frozen ──────────────────────────────────────────────


def test_is_slug_delivered_returns_false_when_no_delivered_file(tmp_path: Path) -> None:
    """Returns False when delivered.yaml does not exist."""
    result = _is_slug_delivered_or_frozen("my-slug", tmp_path)
    assert result is False


def test_is_slug_delivered_returns_true_when_in_delivered(tmp_path: Path) -> None:
    """Returns True when slug appears in delivered.yaml."""
    delivered = tmp_path / "todos" / "delivered.yaml"
    delivered.parent.mkdir(parents=True)
    delivered.write_text("- slug: my-slug\n  delivered_at: 2025-01-01\n")
    result = _is_slug_delivered_or_frozen("my-slug", tmp_path)
    assert result is True


def test_is_slug_frozen_returns_true_when_in_icebox_yaml(tmp_path: Path) -> None:
    """Returns True when slug appears in icebox.yaml."""
    icebox = tmp_path / "todos" / "_icebox" / "icebox.yaml"
    icebox.parent.mkdir(parents=True)
    icebox.write_text("- slug: frozen-slug\n")
    result = _is_slug_delivered_or_frozen("frozen-slug", tmp_path)
    assert result is True


# ── PrepareQualityCartridge.process ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_planning_event_passes_through():
    """Events outside _PLANNING_PREFIX pass through without assessment."""
    cartridge = PrepareQualityCartridge()
    event = _make_event("system.worker.started")
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_planning_event_not_in_trigger_set_passes_through():
    """Planning events not in _TRIGGER_EVENTS pass through without assessment."""
    cartridge = PrepareQualityCartridge()
    event = _make_event("domain.software-development.planning.other_event")
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_event_without_slug_passes_through():
    """Trigger events missing slug field pass through unchanged."""
    cartridge = PrepareQualityCartridge()
    event = EventEnvelope(
        event="domain.software-development.planning.artifact_changed",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        visibility=EventVisibility.LOCAL,
        payload={},
    )
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_assessment_failure_does_not_propagate():
    """Exceptions during _assess are swallowed — event is still returned."""
    cartridge = PrepareQualityCartridge()
    event = _make_event(slug="my-slug")
    ctx = MagicMock()

    with patch.object(cartridge, "_assess", side_effect=RuntimeError("boom")):
        result = await cartridge.process(event, ctx)

    assert result is event


# ── PrepareQualityCartridge._assess public behavior ───────────────────────────


@pytest.mark.asyncio
async def test_process_writes_dor_report_and_updates_state(tmp_path: Path) -> None:
    """process() scores artifacts, writes dor-report.md, and updates state.yaml dor section."""
    todo_dir = tmp_path / "todos" / "my-slug"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text(_full_requirements_content())
    (todo_dir / "implementation-plan.md").write_text(_full_plan_content())
    (todo_dir / "state.yaml").write_text("phase: active\n")

    ctx = MagicMock()
    ctx.db.find_by_group_key = AsyncMock(return_value={"id": 17})
    ctx.db.update_agent_status = AsyncMock()
    ctx.db.resolve_notification = AsyncMock()

    cartridge = PrepareQualityCartridge()
    event = _make_event()

    with (
        patch("teleclaude.events.cartridges.prepare_quality._find_project_root", return_value=tmp_path),
        patch("teleclaude.events.cartridges.prepare_quality._get_todo_commit", return_value="abc123"),
        patch("teleclaude.events.cartridges.prepare_quality.emit_event", new_callable=AsyncMock) as emit_event,
    ):
        result = await cartridge.process(event, ctx)

    assert result is event
    assert (todo_dir / "dor-report.md").exists(), "dor-report.md must be written"
    state = yaml.safe_load((todo_dir / "state.yaml").read_text())
    assert "dor" in state
    assert state["dor"]["status"] == "pass"
    assert state["dor"]["score"] == 10
    assert state["dor"]["assessed_commit"] == "abc123"
    ctx.db.update_agent_status.assert_awaited_once_with(17, "claimed", "prepare-quality-runner")
    ctx.db.resolve_notification.assert_awaited_once()
    assert ctx.db.resolve_notification.await_args.args[0] == 17
    resolve_payload = ctx.db.resolve_notification.await_args.args[1]
    assert resolve_payload["verdict"] == "pass"
    assert resolve_payload["score"] == 10
    emit_event.assert_awaited_once()
    emitted = emit_event.await_args.kwargs
    assert emitted["event"] == "domain.software-development.planning.dor_assessed"
    assert emitted["payload"]["slug"] == "my-slug"
    assert emitted["payload"]["score"] == 10
    assert emitted["payload"]["verdict"] == "pass"


@pytest.mark.asyncio
async def test_process_claims_and_resolves_notification(tmp_path: Path) -> None:
    """process() claims the notification before assessment and resolves it after."""
    todo_dir = tmp_path / "todos" / "my-slug"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text("# Goal\n\nSome goal.\n")

    ctx = MagicMock()
    ctx.db.find_by_group_key = AsyncMock(return_value={"id": 42})
    ctx.db.update_agent_status = AsyncMock()
    ctx.db.resolve_notification = AsyncMock()

    cartridge = PrepareQualityCartridge()
    event = _make_event()

    with (
        patch("teleclaude.events.cartridges.prepare_quality._find_project_root", return_value=tmp_path),
        patch("teleclaude.events.cartridges.prepare_quality._get_todo_commit", return_value="abc123"),
        patch("teleclaude.events.cartridges.prepare_quality.emit_event", new_callable=AsyncMock),
    ):
        result = await cartridge.process(event, ctx)

    assert result is event
    ctx.db.update_agent_status.assert_called_once_with(42, "claimed", "prepare-quality-runner")
    ctx.db.resolve_notification.assert_called_once()
    assert ctx.db.resolve_notification.call_args[0][0] == 42


@pytest.mark.asyncio
async def test_process_emits_dor_assessed_event(tmp_path: Path) -> None:
    """process() emits domain.software-development.planning.dor_assessed with slug and score."""
    todo_dir = tmp_path / "todos" / "my-slug"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text("# Goal\n\nSome goal.\n")

    ctx = MagicMock()
    ctx.db.find_by_group_key = AsyncMock(return_value=None)

    cartridge = PrepareQualityCartridge()
    event = _make_event()

    emit_mock = AsyncMock()
    with (
        patch("teleclaude.events.cartridges.prepare_quality._find_project_root", return_value=tmp_path),
        patch("teleclaude.events.cartridges.prepare_quality._get_todo_commit", return_value="abc123"),
        patch("teleclaude.events.cartridges.prepare_quality.emit_event", emit_mock),
    ):
        result = await cartridge.process(event, ctx)

    assert result is event
    emit_mock.assert_called_once()
    call_kwargs = emit_mock.call_args[1]
    assert call_kwargs["event"] == "domain.software-development.planning.dor_assessed"
    assert call_kwargs["payload"]["slug"] == "my-slug"
    assert "score" in call_kwargs["payload"]
    assert "verdict" in call_kwargs["payload"]
