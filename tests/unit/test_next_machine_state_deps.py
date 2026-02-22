"""Unit tests for state machine refinement features.

Tests for:
- set_item_phase() / get_item_phase() functions
- resolve_slug() with ready-only mode
- Dependency tracking and satisfaction logic
- teleclaude__set_dependencies() validation
- Circular dependency detection
- next_work() without bug check
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from teleclaude.core.db import Db
from teleclaude.core.next_machine import (
    check_dependencies_satisfied,
    detect_circular_dependency,
    get_item_phase,
    is_ready_for_work,
    load_roadmap_deps,
    next_work,
    resolve_slug,
    save_roadmap,
    set_item_phase,
)
from teleclaude.core.next_machine.core import RoadmapEntry

# =============================================================================
# set_item_phase / get_item_phase Tests
# =============================================================================


def test_is_ready_for_work_with_score():
    """Verify is_ready_for_work returns True when pending + dor.score >= 8"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "todos" / "test-item"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        assert is_ready_for_work(tmpdir, "test-item") is True


def test_is_ready_for_work_below_threshold():
    """Verify is_ready_for_work returns False when dor.score < 8"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "todos" / "test-item"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 7}}')

        assert is_ready_for_work(tmpdir, "test-item") is False


def test_is_ready_for_work_no_dor():
    """Verify is_ready_for_work returns False when no dor dict"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "todos" / "test-item"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"phase": "pending"}')

        assert is_ready_for_work(tmpdir, "test-item") is False


def test_is_ready_for_work_in_progress():
    """Verify is_ready_for_work returns False when phase is in_progress"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "todos" / "test-item"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"phase": "in_progress", "dor": {"score": 10}}')

        assert is_ready_for_work(tmpdir, "test-item") is False


def test_set_item_phase_pending_to_in_progress():
    """Verify phase transition from pending to in_progress via state.yaml"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "todos" / "test-item"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        set_item_phase(tmpdir, "test-item", "in_progress")

        phase = get_item_phase(tmpdir, "test-item")
        assert phase == "in_progress"


def test_migration_ready_phase_normalized_to_pending():
    """Verify persisted phase='ready' is normalized to 'pending' on read"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "todos" / "test-item"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"phase": "ready", "dor": {"score": 9}}')

        phase = get_item_phase(tmpdir, "test-item")
        assert phase == "pending"


def test_get_item_phase_missing_state():
    """Verify get_item_phase returns pending when state.yaml doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        phase = get_item_phase(tmpdir, "nonexistent")
        assert phase == "pending"


# =============================================================================
# Dependency Tracking Tests
# =============================================================================


def _write_roadmap_yaml(tmpdir: str, slugs: list[str], deps: dict[str, list[str]] | None = None) -> None:
    """Helper to write roadmap.yaml fixtures in tests."""
    entries = []
    for slug in slugs:
        entry = RoadmapEntry(slug=slug, after=(deps or {}).get(slug, []))
        entries.append(entry)
    save_roadmap(tmpdir, entries)


def test_load_roadmap_deps_missing_file():
    """Verify load_roadmap_deps returns empty dict when file doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        deps = load_roadmap_deps(tmpdir)
        assert deps == {}


def test_save_and_load_roadmap_deps():
    """Verify saving roadmap and loading deps works correctly"""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_deps = {"item-a": ["item-b", "item-c"], "item-d": ["item-a"]}
        _write_roadmap_yaml(tmpdir, ["item-a", "item-b", "item-c", "item-d"], test_deps)

        deps = load_roadmap_deps(tmpdir)
        assert deps == test_deps

        # Verify file format
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.yaml"
        content = roadmap_path.read_text()
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, list)
        assert len(parsed) == 4


def test_check_dependencies_satisfied_no_deps():
    """Verify item with no dependencies is always satisfied"""
    with tempfile.TemporaryDirectory() as tmpdir:
        deps = {}
        result = check_dependencies_satisfied(tmpdir, "test-item", deps)
        assert result is True


def test_check_dependencies_satisfied_all_complete():
    """Verify dependencies are satisfied when all have phase=done"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, ["dep-a", "dep-b", "test-item"])

        # Create state.yaml with phase=done for deps
        for dep in ("dep-a", "dep-b"):
            dep_dir = Path(tmpdir) / "todos" / dep
            dep_dir.mkdir(parents=True, exist_ok=True)
            (dep_dir / "state.yaml").write_text('{"phase": "done"}')

        deps = {"test-item": ["dep-a", "dep-b"]}
        result = check_dependencies_satisfied(tmpdir, "test-item", deps)
        assert result is True


def test_check_dependencies_satisfied_incomplete():
    """Verify dependencies are not satisfied when some are not done"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, ["dep-a", "dep-b", "test-item"])

        # dep-a is done, dep-b is pending
        dep_a_dir = Path(tmpdir) / "todos" / "dep-a"
        dep_a_dir.mkdir(parents=True, exist_ok=True)
        (dep_a_dir / "state.yaml").write_text('{"phase": "done"}')

        dep_b_dir = Path(tmpdir) / "todos" / "dep-b"
        dep_b_dir.mkdir(parents=True, exist_ok=True)
        (dep_b_dir / "state.yaml").write_text('{"phase": "pending"}')

        deps = {"test-item": ["dep-a", "dep-b"]}
        result = check_dependencies_satisfied(tmpdir, "test-item", deps)
        assert result is False


def test_check_dependencies_satisfied_removed():
    """Verify dependencies missing from roadmap are satisfied"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, ["test-item"])

        deps = {"test-item": ["former-dep"]}
        result = check_dependencies_satisfied(tmpdir, "test-item", deps)
        # Should be satisfied since dependency is not in roadmap
        assert result is True


# =============================================================================
# Circular Dependency Detection Tests
# =============================================================================


def test_detect_circular_dependency_direct_cycle():
    """Verify detection of direct circular dependency (A -> B -> A)"""
    deps = {"item-a": ["item-b"]}
    cycle = detect_circular_dependency(deps, "item-b", ["item-a"])
    assert cycle is not None
    assert "item-a" in cycle and "item-b" in cycle


def test_detect_circular_dependency_indirect_cycle():
    """Verify detection of indirect circular dependency (A -> B -> C -> A)"""
    deps = {"item-a": ["item-b"], "item-b": ["item-c"]}
    cycle = detect_circular_dependency(deps, "item-c", ["item-a"])
    assert cycle is not None
    # Cycle exists, exact length may vary based on implementation
    assert "item-a" in cycle
    assert "item-b" in cycle
    assert "item-c" in cycle


def test_detect_circular_dependency_no_cycle():
    """Verify no false positives when there's no cycle"""
    deps = {"item-a": ["item-b"], "item-c": ["item-d"]}
    cycle = detect_circular_dependency(deps, "item-e", ["item-c"])
    assert cycle is None


def test_detect_circular_dependency_self_reference():
    """Verify detection of self-reference (A -> A)"""
    deps = {}
    cycle = detect_circular_dependency(deps, "item-a", ["item-a"])
    assert cycle is not None
    assert "item-a" in cycle


# =============================================================================
# next_work Tests
# =============================================================================


@pytest.mark.asyncio
async def test_next_work_no_bug_check():
    """Verify next_work does not check for bugs"""
    db = MagicMock(spec=Db)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create bugs.md with unchecked items
        bugs_path = Path(tmpdir) / "todos" / "bugs.md"
        bugs_path.parent.mkdir(parents=True, exist_ok=True)
        bugs_path.write_text("# Bugs\n\n- [ ] Fix critical bug\n")

        # Create roadmap with item
        _write_roadmap_yaml(tmpdir, ["test-item"])

        # Create required files
        item_dir = Path(tmpdir) / "todos" / "test-item"
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.yaml").write_text(
            '{"phase": "pending", "dor": {"score": 8}, "build": "pending", "review": "pending"}'
        )

        # Mock git operations
        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=None, cwd=tmpdir)

        # Should NOT dispatch to next-bugs
        assert "next-bugs" not in result
        # Should process the ready item instead
        assert "test-item" in result


@pytest.mark.asyncio
async def test_next_work_respects_dependencies():
    """Verify next_work skips items with unsatisfied dependencies"""
    db = MagicMock(spec=Db)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap with items and dependencies
        deps = {"blocked-item": ["dep-item"]}
        _write_roadmap_yaml(tmpdir, ["dep-item", "blocked-item", "ready-item"], deps)

        # Create state.yaml for each item
        dep_dir = Path(tmpdir) / "todos" / "dep-item"
        dep_dir.mkdir(parents=True, exist_ok=True)
        (dep_dir / "state.yaml").write_text('{"phase": "pending"}')

        blocked_dir = Path(tmpdir) / "todos" / "blocked-item"
        blocked_dir.mkdir(parents=True, exist_ok=True)
        (blocked_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        # Create required files for ready-item
        item_dir = Path(tmpdir) / "todos" / "ready-item"
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.yaml").write_text(
            '{"phase": "pending", "dor": {"score": 8}, "build": "pending", "review": "pending"}'
        )

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=None, cwd=tmpdir)

        # Should select ready-item (no dependencies)
        # Should NOT select blocked-item (has unsatisfied dependency)
        assert "ready-item" in result
        assert "blocked-item" not in result


@pytest.mark.asyncio
async def test_next_work_explicit_slug_checks_dependencies():
    """Verify explicit slug still validates dependencies"""
    db = MagicMock(spec=Db)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap with dependency
        deps = {"blocked-item": ["dep-item"]}
        _write_roadmap_yaml(tmpdir, ["dep-item", "blocked-item"], deps)

        # Create state.yaml for items
        dep_dir = Path(tmpdir) / "todos" / "dep-item"
        dep_dir.mkdir(parents=True, exist_ok=True)
        (dep_dir / "state.yaml").write_text('{"phase": "pending"}')

        blocked_dir = Path(tmpdir) / "todos" / "blocked-item"
        blocked_dir.mkdir(parents=True, exist_ok=True)
        (blocked_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        result = await next_work(db, slug="blocked-item", cwd=tmpdir)

        # Should return error about unsatisfied dependencies
        assert "ERROR:" in result
        assert "DEPS_UNSATISFIED" in result


@pytest.mark.asyncio
async def test_next_work_explicit_slug_rejects_pending_items():
    """Verify explicit slug rejects pending items"""
    db = MagicMock(spec=Db)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap
        _write_roadmap_yaml(tmpdir, ["pending-item", "ready-item"])

        # Create state.yaml with phase=pending
        pend_dir = Path(tmpdir) / "todos" / "pending-item"
        pend_dir.mkdir(parents=True, exist_ok=True)
        (pend_dir / "state.yaml").write_text('{"phase": "pending"}')

        result = await next_work(db, slug="pending-item", cwd=tmpdir)

        # Should return error indicating item is not ready
        assert "ERROR:" in result
        assert "ITEM_NOT_READY" in result
        assert "pending" in result


@pytest.mark.asyncio
async def test_next_work_review_includes_merge_base_note():
    """Verify next_work review dispatch includes merge-base guard note."""
    db = MagicMock(spec=Db)
    slug = "review-item"

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap with ready item
        _write_roadmap_yaml(tmpdir, [slug])

        # Create required files in main repo
        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        # Create worktree state with build complete and review pending
        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "pending"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core.is_main_ahead", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "next-review" in result
        assert "merge-base" in result


@pytest.mark.asyncio
async def test_next_work_blocks_when_stash_debt_exists():
    """next_work should hard-stop when repository stash is non-empty."""
    db = MagicMock(spec=Db)
    slug = "stash-blocked"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.get_stash_entries", return_value=["stash@{0}: WIP on foo"]),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "ERROR: STASH_DEBT" in result


@pytest.mark.asyncio
async def test_next_work_does_not_block_review_when_main_ahead():
    """Verify next_work stays worktree-local and still dispatches review."""
    db = MagicMock(spec=Db)
    slug = "review-blocked"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "pending"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.ensure_worktree", return_value=False),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core.is_main_ahead", return_value=True),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "next-review" in result


@pytest.mark.asyncio
async def test_next_work_blocks_when_review_round_limit_reached():
    """Verify next_work stops when next review would exceed max rounds."""
    db = MagicMock(spec=Db)
    slug = "review-round-limit"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text(
            '{"build":"complete","review":"pending","review_round":2,"max_review_rounds":2}'
        )

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.is_main_ahead", return_value=False),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "ERROR:" in result
        assert "REVIEW_ROUND_LIMIT" in result


@pytest.mark.asyncio
async def test_next_work_finalize_next_call_without_slug():
    """Finalize dispatch should call next_work without slug."""
    db = MagicMock(spec=Db)
    slug = "final-item"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.yaml").write_text('{"phase": "pending", "dor": {"score": 8}}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "approved"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

    assert 'command="/next-finalize"' in result
    assert "Call teleclaude__next_work()" in result
    assert "Call teleclaude__next_work(slug=" not in result


# =============================================================================
# resolve_slug Tests (ready_only mode)
# =============================================================================


def test_resolve_slug_ready_only_matches_ready_items():
    """Verify ready_only=True only matches items with pending phase + dor.score >= 8"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, ["pending-item", "ready-item", "in-progress-item", "done-item"])

        # Create state.yaml for each item
        states = {
            "pending-item": '{"phase": "pending"}',
            "ready-item": '{"phase": "pending", "dor": {"score": 8}}',
            "in-progress-item": '{"phase": "in_progress"}',
            "done-item": '{"phase": "done"}',
        }
        for slug_name, state in states.items():
            d = Path(tmpdir) / "todos" / slug_name
            d.mkdir(parents=True, exist_ok=True)
            (d / "state.yaml").write_text(state)

        slug, is_ready, _ = resolve_slug(tmpdir, slug=None, ready_only=True)

        # Should only match the first ready item (pending + dor.score >= 8)
        assert slug == "ready-item"
        assert is_ready is True


def test_resolve_slug_ready_only_no_ready_items():
    """Verify ready_only=True returns None when no ready items exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, ["pending-item", "in-progress-item"])

        for slug_name, phase in [("pending-item", "pending"), ("in-progress-item", "in_progress")]:
            d = Path(tmpdir) / "todos" / slug_name
            d.mkdir(parents=True, exist_ok=True)
            (d / "state.yaml").write_text(f'{{"phase": "{phase}"}}')

        slug, is_ready, desc = resolve_slug(tmpdir, slug=None, ready_only=True)

        assert slug is None
        assert is_ready is False


def test_resolve_slug_ready_only_skips_pending():
    """Verify ready_only=True skips pending items without sufficient dor score"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, ["pending-item", "ready-item"])

        states = {
            "pending-item": '{"phase": "pending"}',
            "ready-item": '{"phase": "pending", "dor": {"score": 8}}',
        }
        for slug_name, state in states.items():
            d = Path(tmpdir) / "todos" / slug_name
            d.mkdir(parents=True, exist_ok=True)
            (d / "state.yaml").write_text(state)

        slug, _, _ = resolve_slug(tmpdir, slug=None, ready_only=True)

        # Should skip pending (no dor score) and match ready (dor.score >= 8)
        assert slug == "ready-item"


def test_resolve_slug_ready_only_skips_in_progress():
    """Verify ready_only=True skips in_progress items"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, ["in-progress-item", "ready-item"])

        states = {
            "in-progress-item": '{"phase": "in_progress"}',
            "ready-item": '{"phase": "pending", "dor": {"score": 8}}',
        }
        for slug_name, state in states.items():
            d = Path(tmpdir) / "todos" / slug_name
            d.mkdir(parents=True, exist_ok=True)
            (d / "state.yaml").write_text(state)

        slug, _, _ = resolve_slug(tmpdir, slug=None, ready_only=True)

        # Should skip in-progress and match ready (pending + dor.score >= 8)
        assert slug == "ready-item"
