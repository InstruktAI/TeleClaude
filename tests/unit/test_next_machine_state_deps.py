"""Unit tests for state machine refinement features.

Tests for:
- resolve_slug() with ready-only mode
- Dependency tracking and satisfaction logic
- telec todo set-deps() validation
- Circular dependency detection
- next_work() without bug check
"""

import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from git.exc import GitCommandError

from teleclaude.core.db import Db
from teleclaude.core.next_machine import (
    PhaseName,
    PhaseStatus,
    check_dependencies_satisfied,
    detect_circular_dependency,
    is_ready_for_work,
    load_roadmap_deps,
    mark_finalize_ready,
    mark_phase,
    next_work,
    read_phase_state,
    resolve_slug,
    save_roadmap,
)
from teleclaude.core.next_machine.core import RoadmapEntry, run_build_gates

# Realistic file content that passes scaffold detection
_REAL_REQUIREMENTS = "# Requirements\n\n## Goal\n\nRefactor cache layer for transparency.\n"
_REAL_IMPL_PLAN = "# Implementation Plan\n\n## Overview\n\nAdd cache status headers via middleware.\n"

# =============================================================================
# Item Readiness Tests
# =============================================================================


def test_is_ready_for_work_with_score():
    """Verify is_ready_for_work returns True when build pending + dor.score >= 8"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "todos" / "test-item"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}}')

        assert is_ready_for_work(tmpdir, "test-item") is True


def test_is_ready_for_work_below_threshold():
    """Verify is_ready_for_work returns False when dor.score < 8"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "todos" / "test-item"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 7}}')

        assert is_ready_for_work(tmpdir, "test-item") is False


def test_is_ready_for_work_no_dor():
    """Verify is_ready_for_work returns False when no dor dict"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "todos" / "test-item"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "pending"}')

        assert is_ready_for_work(tmpdir, "test-item") is False


def test_is_ready_for_work_started():
    """Verify is_ready_for_work returns False when build is started"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "todos" / "test-item"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "started", "dor": {"score": 10}}')

        assert is_ready_for_work(tmpdir, "test-item") is False


def test_mark_phase_build_started():
    """Verify build status transition from pending to started via mark_phase"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "todos" / "test-item"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}}')

        mark_phase(tmpdir, "test-item", PhaseName.BUILD.value, PhaseStatus.STARTED.value)

        state = read_phase_state(tmpdir, "test-item")
        assert state.get(PhaseName.BUILD.value) == PhaseStatus.STARTED.value


def test_read_phase_state_defaults():
    """Verify read_phase_state returns defaults when state.yaml doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = read_phase_state(tmpdir, "nonexistent")
        assert state.get(PhaseName.BUILD.value) == PhaseStatus.PENDING.value
        assert state.get(PhaseName.REVIEW.value) == PhaseStatus.PENDING.value


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
    """Verify dependencies are satisfied when all have review=approved"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, ["dep-a", "dep-b", "test-item"])

        # Create state.yaml with review=approved for deps
        for dep in ("dep-a", "dep-b"):
            dep_dir = Path(tmpdir) / "todos" / dep
            dep_dir.mkdir(parents=True, exist_ok=True)
            (dep_dir / "state.yaml").write_text('{"review": "approved"}')

        deps = {"test-item": ["dep-a", "dep-b"]}
        result = check_dependencies_satisfied(tmpdir, "test-item", deps)
        assert result is True


def test_check_dependencies_satisfied_incomplete():
    """Verify dependencies are not satisfied when some are not approved"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, ["dep-a", "dep-b", "test-item"])

        # dep-a is approved, dep-b is pending review
        dep_a_dir = Path(tmpdir) / "todos" / "dep-a"
        dep_a_dir.mkdir(parents=True, exist_ok=True)
        (dep_a_dir / "state.yaml").write_text('{"review": "approved"}')

        dep_b_dir = Path(tmpdir) / "todos" / "dep-b"
        dep_b_dir.mkdir(parents=True, exist_ok=True)
        (dep_b_dir / "state.yaml").write_text('{"review": "pending"}')

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
        (item_dir / "requirements.md").write_text(_REAL_REQUIREMENTS)
        (item_dir / "implementation-plan.md").write_text(_REAL_IMPL_PLAN)
        (item_dir / "state.yaml").write_text('{"build": "pending", "review": "pending", "dor": {"score": 8}}')

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
        (dep_dir / "state.yaml").write_text('{"build": "pending", "review": "pending"}')

        blocked_dir = Path(tmpdir) / "todos" / "blocked-item"
        blocked_dir.mkdir(parents=True, exist_ok=True)
        (blocked_dir / "state.yaml").write_text('{"build": "pending", "review": "pending", "dor": {"score": 8}}')

        # Create required files for ready-item
        item_dir = Path(tmpdir) / "todos" / "ready-item"
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text(_REAL_REQUIREMENTS)
        (item_dir / "implementation-plan.md").write_text(_REAL_IMPL_PLAN)
        (item_dir / "state.yaml").write_text('{"build": "pending", "review": "pending", "dor": {"score": 8}}')

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
        (dep_dir / "state.yaml").write_text('{"build": "pending", "review": "pending"}')

        blocked_dir = Path(tmpdir) / "todos" / "blocked-item"
        blocked_dir.mkdir(parents=True, exist_ok=True)
        (blocked_dir / "state.yaml").write_text('{"build": "pending", "review": "pending", "dor": {"score": 8}}')

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

        # Create state.yaml with build=pending
        pend_dir = Path(tmpdir) / "todos" / "pending-item"
        pend_dir.mkdir(parents=True, exist_ok=True)
        (pend_dir / "state.yaml").write_text('{"build": "pending", "review": "pending"}')

        result = await next_work(db, slug="pending-item", cwd=tmpdir)

        # Should return error indicating item is not ready
        assert "ERROR:" in result
        assert "ITEM_NOT_READY" in result
        assert "pending" in result


@pytest.mark.asyncio
async def test_next_work_explicit_holder_slug_resolves_first_runnable_child_by_group():
    """Explicit holder slug should transparently resolve to first runnable grouped child."""
    db = MagicMock(spec=Db)

    with tempfile.TemporaryDirectory() as tmpdir:
        entries = [
            RoadmapEntry(slug="child-not-ready", group="holder-item"),
            RoadmapEntry(slug="child-ready", group="holder-item"),
        ]
        save_roadmap(tmpdir, entries)

        not_ready_dir = Path(tmpdir) / "todos" / "child-not-ready"
        not_ready_dir.mkdir(parents=True, exist_ok=True)
        (not_ready_dir / "state.yaml").write_text('{"build": "pending", "review": "pending"}')

        ready_dir = Path(tmpdir) / "todos" / "child-ready"
        ready_dir.mkdir(parents=True, exist_ok=True)
        (ready_dir / "requirements.md").write_text(_REAL_REQUIREMENTS)
        (ready_dir / "implementation-plan.md").write_text(_REAL_IMPL_PLAN)
        (ready_dir / "state.yaml").write_text('{"build": "pending", "review": "pending", "dor": {"score": 8}}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug="holder-item", cwd=tmpdir)

        assert "ERROR:" not in result
        assert "child-ready" in result
        assert "child-not-ready" not in result


@pytest.mark.asyncio
async def test_next_work_explicit_holder_slug_not_ready_when_no_runnable_children():
    """Holder with children but no ready child should return ITEM_NOT_READY."""
    db = MagicMock(spec=Db)

    with tempfile.TemporaryDirectory() as tmpdir:
        entries = [
            RoadmapEntry(slug="child-a"),
            RoadmapEntry(slug="child-b"),
        ]
        save_roadmap(tmpdir, entries)

        holder_dir = Path(tmpdir) / "todos" / "holder-item"
        holder_dir.mkdir(parents=True, exist_ok=True)
        (holder_dir / "state.yaml").write_text(
            '{"build":"pending","review":"pending","breakdown":{"assessed":true,"todos":["child-a","child-b"]}}'
        )

        child_a_dir = Path(tmpdir) / "todos" / "child-a"
        child_a_dir.mkdir(parents=True, exist_ok=True)
        (child_a_dir / "state.yaml").write_text('{"build": "pending", "review": "pending"}')

        child_b_dir = Path(tmpdir) / "todos" / "child-b"
        child_b_dir.mkdir(parents=True, exist_ok=True)
        (child_b_dir / "state.yaml").write_text('{"build": "pending", "review": "pending", "dor": {"score": 7}}')

        result = await next_work(db, slug="holder-item", cwd=tmpdir)

        assert "ERROR:" in result
        assert "ITEM_NOT_READY" in result
        assert "holder-item" in result


@pytest.mark.asyncio
async def test_next_work_explicit_holder_slug_deps_unsatisfied_when_children_blocked():
    """Holder with ready children blocked by deps should return DEPS_UNSATISFIED."""
    db = MagicMock(spec=Db)

    with tempfile.TemporaryDirectory() as tmpdir:
        entries = [
            RoadmapEntry(slug="dep-item"),
            RoadmapEntry(slug="child-ready", group="holder-item", after=["dep-item"]),
        ]
        save_roadmap(tmpdir, entries)

        dep_dir = Path(tmpdir) / "todos" / "dep-item"
        dep_dir.mkdir(parents=True, exist_ok=True)
        (dep_dir / "state.yaml").write_text('{"build": "pending", "review": "pending"}')

        child_dir = Path(tmpdir) / "todos" / "child-ready"
        child_dir.mkdir(parents=True, exist_ok=True)
        (child_dir / "state.yaml").write_text('{"build": "pending", "review": "pending", "dor": {"score": 8}}')

        result = await next_work(db, slug="holder-item", cwd=tmpdir)

        assert "ERROR:" in result
        assert "DEPS_UNSATISFIED" in result
        assert "holder-item" in result


@pytest.mark.asyncio
async def test_next_work_explicit_bug_slug_allows_pending_items():
    """Explicit bug slugs should skip DOR readiness gating."""
    db = MagicMock(spec=Db)
    slug = "fix-bug"

    with tempfile.TemporaryDirectory() as tmpdir:
        todo_dir = Path(tmpdir) / "todos" / slug
        todo_dir.mkdir(parents=True, exist_ok=True)
        (todo_dir / "bug.md").write_text("# Bug\n")
        (todo_dir / "state.yaml").write_text('{"build": "pending", "review": "pending", "dor": null}')

        # Ensure sync paths have a destination to copy bug.md into.
        (Path(tmpdir) / "trees" / slug).mkdir(parents=True, exist_ok=True)

        with (
            patch(
                "teleclaude.core.next_machine.core.ensure_worktree_with_policy_async",
                new=AsyncMock(return_value=MagicMock(created=False, prepared=False, prep_reason="mocked")),
            ),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "ERROR: ITEM_NOT_READY" not in result
        assert "next-bugs-fix" in result


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_next_work_explicit_bug_slug_with_worktree_cwd_skips_dor_gate():
    """Bug start should work when cwd points at trees/{slug} worktree."""
    db = MagicMock(spec=Db)
    slug = "fix-bug"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create a real git repo + worktree so cwd normalization can resolve
        # project root from a worktree path.
        subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.email", "tests@example.com"],
            cwd=tmpdir,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Tests"],
            cwd=tmpdir,
            check=True,
            capture_output=True,
            text=True,
        )
        (tmp_path / "README.md").write_text("# Test\n")
        subprocess.run(["git", "add", "README.md"], cwd=tmpdir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "worktree", "add", f"trees/{slug}", "-b", slug],
            cwd=tmpdir,
            check=True,
            capture_output=True,
            text=True,
        )

        todo_dir = tmp_path / "todos" / slug
        todo_dir.mkdir(parents=True, exist_ok=True)
        (todo_dir / "bug.md").write_text("# Bug\n")
        (todo_dir / "state.yaml").write_text('{"build": "pending", "review": "pending", "dor": null}')

        with (
            patch(
                "teleclaude.core.next_machine.core.ensure_worktree_with_policy_async",
                new=AsyncMock(return_value=MagicMock(created=False, prepared=False, prep_reason="mocked")),
            ),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=str(tmp_path / "trees" / slug))

        assert "ERROR: ITEM_NOT_READY" not in result
        assert "next-bugs-fix" in result


def test_run_build_gates_skips_demo_validation_for_bug(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Bug workflow should not fail build gates for missing demo.md."""
    slug = "fix-bug"
    bug_dir = tmp_path / "todos" / slug
    bug_dir.mkdir(parents=True, exist_ok=True)
    (bug_dir / "bug.md").write_text("# Bug\n")

    commands: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(cmd)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("teleclaude.core.next_machine.core.subprocess.run", _fake_run)

    passed, output = run_build_gates(str(tmp_path), slug)

    assert passed is True
    assert commands == [["make", "test"]]
    assert "GATE SKIPPED: demo validate (bug workflow)" in output


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
        (item_dir / "requirements.md").write_text(_REAL_REQUIREMENTS)
        (item_dir / "implementation-plan.md").write_text(_REAL_IMPL_PLAN)
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        # Create worktree state with build complete and review pending
        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "pending"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "mocked")),
            patch("teleclaude.core.next_machine.core.verify_artifacts", return_value=(True, "mocked")),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "next-review-build" in result
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
        (item_dir / "requirements.md").write_text(_REAL_REQUIREMENTS)
        (item_dir / "implementation-plan.md").write_text(_REAL_IMPL_PLAN)
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

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
        (item_dir / "requirements.md").write_text(_REAL_REQUIREMENTS)
        (item_dir / "implementation-plan.md").write_text(_REAL_IMPL_PLAN)
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "pending"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch(
                "teleclaude.core.next_machine.core.ensure_worktree_with_policy_async",
                new=AsyncMock(return_value=MagicMock(created=False, prepared=False, prep_reason="mocked")),
            ),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "mocked")),
            patch("teleclaude.core.next_machine.core.verify_artifacts", return_value=(True, "mocked")),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "next-review-build" in result


@pytest.mark.asyncio
async def test_next_work_blocks_when_review_round_limit_reached():
    """Verify next_work stops when next review would exceed max rounds."""
    db = MagicMock(spec=Db)
    slug = "review-round-limit"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text(_REAL_REQUIREMENTS)
        (item_dir / "implementation-plan.md").write_text(_REAL_IMPL_PLAN)
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text(
            '{"build":"complete","review":"pending","review_round":2,"max_review_rounds":2}'
        )

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "mocked")),
            patch("teleclaude.core.next_machine.core.verify_artifacts", return_value=(True, "mocked")),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "ERROR:" in result
        assert "REVIEW_ROUND_LIMIT" in result


@pytest.mark.asyncio
async def test_next_work_returns_structured_error_when_worktree_setup_throws():
    """Unexpected worktree setup exceptions should not escape as bare 500s."""
    db = MagicMock(spec=Db)
    slug = "worktree-setup-failure"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text(_REAL_REQUIREMENTS)
        (item_dir / "implementation-plan.md").write_text(_REAL_IMPL_PLAN)
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        with patch(
            "teleclaude.core.next_machine.core.ensure_worktree_with_policy_async",
            new=AsyncMock(
                side_effect=GitCommandError(
                    "git worktree add trees/worktree-setup-failure -b worktree-setup-failure",
                    255,
                    stderr="fatal: a branch named 'worktree-setup-failure' already exists",
                )
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

    assert "ERROR: WORKTREE_SETUP_FAILED" in result
    assert "GitCommandError" in result
    assert "branch named 'worktree-setup-failure' already exists" in result


@pytest.mark.asyncio
async def test_next_work_finalize_next_call_without_slug():
    """Finalize dispatch should rerun the same slug so handoff is consumed before the queue advances."""
    db = MagicMock(spec=Db)
    slug = "final-item"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text(_REAL_REQUIREMENTS)
        (item_dir / "implementation-plan.md").write_text(_REAL_IMPL_PLAN)
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "approved"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "mocked")),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

    assert '--command "/next-finalize"' in result
    assert f"Call telec todo work {slug}" in result
    assert "FINALIZE_READY: final-item" in result
    assert "telec todo integrate" not in result


@pytest.mark.asyncio
async def test_next_work_approved_review_repairs_build_drift_and_dispatches_finalize():
    """Approved review should not regress to build when build state drifted."""
    db = MagicMock(spec=Db)
    slug = "final-item-repair-build"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text(_REAL_REQUIREMENTS)
        (item_dir / "implementation-plan.md").write_text(_REAL_IMPL_PLAN)
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text(
            '{"build":"started","review":"approved","review_baseline_commit":"head-sha"}'
        )

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core._get_head_commit", return_value="head-sha"),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        repaired_state = yaml.safe_load((state_dir / "state.yaml").read_text())
        assert repaired_state["build"] == "complete"
        assert repaired_state["review"] == "approved"
        assert '--command "/next-finalize"' in result
        assert "next-build" not in result


@pytest.mark.asyncio
async def test_next_work_stale_review_approval_routes_back_to_review():
    """Approval baseline drift should clear approval and require re-review."""
    db = MagicMock(spec=Db)
    slug = "review-stale-baseline"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text(_REAL_REQUIREMENTS)
        (item_dir / "implementation-plan.md").write_text(_REAL_IMPL_PLAN)
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text(
            '{"build":"complete","review":"approved","review_baseline_commit":"old-sha"}'
        )

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core._get_head_commit", return_value="new-sha"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "mocked")),
            patch("teleclaude.core.next_machine.core.verify_artifacts", return_value=(True, "mocked")),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        updated_state = yaml.safe_load((state_dir / "state.yaml").read_text())
        assert updated_state["review"] == "pending"
        assert "next-review-build" in result
        assert "next-finalize" not in result
        assert "next-build" not in result


# =============================================================================
# resolve_slug Tests (ready_only mode)
# =============================================================================


def test_resolve_slug_ready_only_matches_ready_items():
    """Verify ready_only=True only matches items with build pending + dor.score >= 8"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, ["pending-item", "ready-item", "in-progress-item", "done-item"])

        # Create state.yaml for each item
        states = {
            "pending-item": '{"build": "pending", "review": "pending"}',
            "ready-item": '{"build": "pending", "review": "pending", "dor": {"score": 8}}',
            "in-progress-item": '{"build": "started", "review": "pending"}',
            "done-item": '{"build": "complete", "review": "approved"}',
        }
        for slug_name, state in states.items():
            d = Path(tmpdir) / "todos" / slug_name
            d.mkdir(parents=True, exist_ok=True)
            (d / "state.yaml").write_text(state)

        slug, is_ready, _ = resolve_slug(tmpdir, slug=None, ready_only=True)

        # Should only match the first ready item (build pending + dor.score >= 8)
        assert slug == "ready-item"
        assert is_ready is True


def test_resolve_slug_ready_only_no_ready_items():
    """Verify ready_only=True returns None when no ready items exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, ["pending-item", "in-progress-item"])

        for slug_name, build_status in [("pending-item", "pending"), ("in-progress-item", "started")]:
            d = Path(tmpdir) / "todos" / slug_name
            d.mkdir(parents=True, exist_ok=True)
            (d / "state.yaml").write_text(f'{{"build": "{build_status}", "review": "pending"}}')

        slug, is_ready, desc = resolve_slug(tmpdir, slug=None, ready_only=True)

        assert slug is None
        assert is_ready is False


def test_resolve_slug_ready_only_skips_pending():
    """Verify ready_only=True skips pending items without sufficient dor score"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, ["pending-item", "ready-item"])

        states = {
            "pending-item": '{"build": "pending", "review": "pending"}',
            "ready-item": '{"build": "pending", "review": "pending", "dor": {"score": 8}}',
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
            "in-progress-item": '{"build": "started", "review": "pending"}',
            "ready-item": '{"build": "pending", "review": "pending", "dor": {"score": 8}}',
        }
        for slug_name, state in states.items():
            d = Path(tmpdir) / "todos" / slug_name
            d.mkdir(parents=True, exist_ok=True)
            (d / "state.yaml").write_text(state)

        slug, _, _ = resolve_slug(tmpdir, slug=None, ready_only=True)

        # Should skip in-progress and match ready (build pending + dor.score >= 8)
        assert slug == "ready-item"


# =============================================================================
# Integration Event Emission Tests (I3)
# =============================================================================


@pytest.mark.asyncio
async def test_finalize_dispatch_emits_only_review_approved():
    """Finalize dispatch records review approval but defers handoff events until FINALIZE_READY is consumed."""
    db = MagicMock(spec=Db)
    slug = "emit-all-events-item"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text(_REAL_REQUIREMENTS)
        (item_dir / "implementation-plan.md").write_text(_REAL_IMPL_PLAN)
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "approved"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "mocked")),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
            patch(
                "teleclaude.core.next_machine.core.emit_review_approved",
                new_callable=AsyncMock,
            ) as mock_review_approved,
            patch(
                "teleclaude.core.next_machine.core.emit_branch_pushed",
                new_callable=AsyncMock,
            ) as mock_branch_pushed,
            patch(
                "teleclaude.core.next_machine.core.emit_deployment_started",
                new_callable=AsyncMock,
            ) as mock_deployment_started,
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

    assert '--command "/next-finalize"' in result

    mock_review_approved.assert_called_once()
    call_kwargs = mock_review_approved.call_args
    assert call_kwargs.kwargs["slug"] == slug
    assert call_kwargs.kwargs["reviewer_session_id"]  # must be non-empty
    assert isinstance(call_kwargs.kwargs["review_round"], int)

    mock_branch_pushed.assert_not_called()
    mock_deployment_started.assert_not_called()
    assert f"telec todo work {slug}" in result


@pytest.mark.asyncio
async def test_finalize_ready_slug_rerun_emits_handoff_events():
    """A slug-specific rerun after FINALIZE_READY consumes state and emits handoff events exactly once."""
    db = MagicMock(spec=Db)
    slug = "handoff-item"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text(_REAL_REQUIREMENTS)
        (item_dir / "implementation-plan.md").write_text(_REAL_IMPL_PLAN)
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text(
            '{"build": "complete", "review": "approved", "finalize": '
            '{"status": "ready", "branch": "handoff-item", "sha": "abc1234def567890", '
            '"ready_at": "2026-03-08T08:00:00+00:00", "worker_session_id": "worker-123"}}'
        )

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "mocked")),
            patch(
                "teleclaude.core.next_machine.core.emit_review_approved",
                new_callable=AsyncMock,
            ) as mock_review_approved,
            patch(
                "teleclaude.core.next_machine.core.emit_branch_pushed",
                new_callable=AsyncMock,
            ) as mock_branch_pushed,
            patch(
                "teleclaude.core.next_machine.core.emit_deployment_started",
                new_callable=AsyncMock,
            ) as mock_deployment_started,
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert result.startswith(f"FINALIZE HANDOFF COMPLETE: {slug}")
        assert "Call telec todo work" in result
        mock_review_approved.assert_not_called()
        mock_branch_pushed.assert_called_once()
        mock_deployment_started.assert_called_once()
        ds_kwargs = mock_deployment_started.call_args.kwargs
        assert ds_kwargs["slug"] == slug
        assert ds_kwargs["worker_session_id"] == "worker-123"
        updated = yaml.safe_load((state_dir / "state.yaml").read_text())
        assert updated["finalize"]["status"] == "handed_off"


def test_mark_finalize_ready_requires_pushed_branch_and_records_state():
    """Finalize readiness is only durable once the finalized branch head is published to origin."""
    slug = "ready-item"

    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "approved"}')

        with (
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._get_head_commit", return_value="abc123"),
            patch("teleclaude.core.next_machine.core._get_ref_commit", return_value="abc123"),
            patch("teleclaude.core.next_machine.core._get_remote_branch_head", return_value="abc123"),
        ):
            state = mark_finalize_ready(tmpdir, slug, worker_session_id="worker-42")

    finalize = state["finalize"]
    assert isinstance(finalize, dict)
    assert finalize["status"] == "ready"
    assert finalize["branch"] == slug
    assert finalize["sha"] == "abc123"
    assert finalize["worker_session_id"] == "worker-42"


# =============================================================================
# End-to-End Integration Event Chain Test (I4)
# =============================================================================


def test_cartridge_ingest_callback_chains_to_ready_projection():
    """Wires cartridge + IntegrationEventService: 3 valid events → READY → spawn."""
    from datetime import UTC, datetime

    from teleclaude.core.integration import IntegrationEventService

    service = IntegrationEventService.create(
        reachability_checker=lambda _b, _s, _r: True,
        integrated_checker=lambda _s, _r: False,
    )

    ts = datetime.now(UTC).isoformat()
    slug = "chain-test-slug"
    branch = "chain-test-slug"
    sha = "feedc0ffee1234567890abcdef012345"
    session_id = "test-session"

    # Inject all 3 events directly into the service (bypass emit/pipeline)
    result1 = service.ingest_raw(
        "review_approved",
        {"slug": slug, "approved_at": ts, "review_round": 1, "reviewer_session_id": session_id},
    )
    assert result1.status == "APPENDED", f"review_approved rejected: {result1}"

    result2 = service.ingest_raw(
        "branch_pushed",
        {"branch": branch, "sha": sha, "remote": "origin", "pushed_at": ts, "pusher": session_id},
    )
    assert result2.status == "APPENDED", f"branch_pushed rejected: {result2}"

    result3 = service.ingest_raw(
        "finalize_ready",
        {
            "slug": slug,
            "branch": branch,
            "sha": sha,
            "worker_session_id": session_id,
            "orchestrator_session_id": session_id,
            "ready_at": ts,
        },
    )
    assert result3.status == "APPENDED", f"finalize_ready rejected: {result3}"
    assert len(result3.transitioned_to_ready) == 1, "Expected candidate to reach READY after 3rd event"

    ready = result3.transitioned_to_ready[0]
    assert ready.key.slug == slug
    assert ready.key.branch == branch
    assert ready.key.sha == sha
