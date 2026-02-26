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

from teleclaude.core.db import Db
from teleclaude.core.next_machine import (
    PhaseName,
    PhaseStatus,
    check_dependencies_satisfied,
    detect_circular_dependency,
    is_ready_for_work,
    load_roadmap_deps,
    mark_phase,
    next_work,
    read_phase_state,
    resolve_slug,
    save_roadmap,
)
from teleclaude.core.next_machine.core import RoadmapEntry, run_build_gates

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
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
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
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
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
        (ready_dir / "requirements.md").write_text("# Requirements\n")
        (ready_dir / "implementation-plan.md").write_text("# Plan\n")
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
            patch("teleclaude.core.next_machine.core.ensure_worktree_async", new=AsyncMock(return_value=False)),
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
            patch("teleclaude.core.next_machine.core.ensure_worktree_async", new=AsyncMock(return_value=False)),
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
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        # Create worktree state with build complete and review pending
        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "pending"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core.is_main_ahead", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "mocked")),
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
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "pending"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.ensure_worktree", return_value=False),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core.is_main_ahead", return_value=True),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "mocked")),
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
            patch("teleclaude.core.next_machine.core.is_main_ahead", return_value=False),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "mocked")),
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
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "approved"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "mocked")),
            patch("teleclaude.core.next_machine.core.get_finalize_canonical_dirty_paths", return_value=[]),
            patch("teleclaude.core.next_machine.core.is_main_ahead", return_value=False),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir, caller_session_id="orchestrator-session")

    assert '--command "/next-finalize"' in result
    assert "Call telec todo work" in result
    assert "Call telec todo work(slug=" not in result
    assert "FINALIZE_READY: final-item" in result
    assert "telec roadmap deliver final-item" in result


@pytest.mark.asyncio
async def test_next_work_finalize_blocks_on_dirty_canonical_main():
    """Finalize dispatch should fail fast when canonical main is dirty."""
    db = MagicMock(spec=Db)
    slug = "final-item-dirty-main"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
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
                "teleclaude.core.next_machine.core.get_finalize_canonical_dirty_paths",
                return_value=["pyproject.toml"],
            ),
            patch("teleclaude.core.next_machine.core.is_main_ahead", return_value=False),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir, caller_session_id="orchestrator-session")

    assert "ERROR: FINALIZE_PRECONDITION_DIRTY_CANONICAL_MAIN" in result
    assert "pyproject.toml" in result


@pytest.mark.asyncio
async def test_next_work_finalize_blocks_when_main_ahead():
    """Finalize dispatch should fail fast when canonical main is ahead of slug branch."""
    db = MagicMock(spec=Db)
    slug = "final-item-main-ahead"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "approved"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "mocked")),
            patch("teleclaude.core.next_machine.core.get_finalize_canonical_dirty_paths", return_value=[]),
            patch("teleclaude.core.next_machine.core.is_main_ahead", return_value=True),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir, caller_session_id="orchestrator-session")

    assert "ERROR: FINALIZE_PRECONDITION_MAIN_AHEAD" in result


@pytest.mark.asyncio
async def test_next_work_finalize_blocks_on_unknown_canonical_git_state():
    """Finalize dispatch should fail when canonical git state cannot be inspected."""
    db = MagicMock(spec=Db)
    slug = "final-item-git-unknown"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "approved"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "mocked")),
            patch("teleclaude.core.next_machine.core.acquire_finalize_lock", return_value=None),
            patch("teleclaude.core.next_machine.core.release_finalize_lock") as release_lock,
            patch("teleclaude.core.next_machine.core.get_finalize_canonical_dirty_paths", return_value=None),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir, caller_session_id="orchestrator-session")

    assert "ERROR: FINALIZE_PRECONDITION_GIT_STATE_UNKNOWN" in result
    release_lock.assert_called_once_with(tmpdir, "orchestrator-session")


@pytest.mark.asyncio
async def test_next_work_finalize_blocks_on_unknown_main_ahead_state():
    """Finalize dispatch should fail when main-ahead state cannot be determined."""
    db = MagicMock(spec=Db)
    slug = "final-item-main-ahead-unknown"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.yaml").write_text('{"build": "pending", "dor": {"score": 8}, "review": "pending"}')

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.yaml").write_text('{"build": "complete", "review": "approved"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.run_build_gates", return_value=(True, "mocked")),
            patch("teleclaude.core.next_machine.core.acquire_finalize_lock", return_value=None),
            patch("teleclaude.core.next_machine.core.release_finalize_lock") as release_lock,
            patch("teleclaude.core.next_machine.core.get_finalize_canonical_dirty_paths", return_value=[]),
            patch("teleclaude.core.next_machine.core.is_main_ahead", return_value=None),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir, caller_session_id="orchestrator-session")

    assert "ERROR: FINALIZE_PRECONDITION_GIT_STATE_UNKNOWN" in result
    release_lock.assert_called_once_with(tmpdir, "orchestrator-session")


@pytest.mark.asyncio
async def test_next_work_finalize_returns_locked_before_preconditions():
    """Finalize lock contention should short-circuit canonical precondition checks."""
    db = MagicMock(spec=Db)
    slug = "final-item-locked"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
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
                "teleclaude.core.next_machine.core.acquire_finalize_lock",
                return_value="FINALIZE_LOCKED\nAnother finalize is in progress.",
            ),
            patch(
                "teleclaude.core.next_machine.core.check_finalize_preconditions",
                side_effect=AssertionError("preconditions must not run when finalize lock is already held"),
            ),
            patch(
                "teleclaude.core.next_machine.core.compose_agent_guidance",
                new=AsyncMock(return_value="AGENT SELECTION GUIDANCE:\n- CLAUDE: ..."),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir, caller_session_id="orchestrator-session")

    assert "FINALIZE_LOCKED" in result


@pytest.mark.asyncio
async def test_next_work_finalize_requires_caller_session_id():
    """Finalize dispatch must require caller session identity for lock ownership."""
    db = MagicMock(spec=Db)
    slug = "final-item-no-caller"

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, [slug])

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
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
            result = await next_work(db, slug=slug, cwd=tmpdir, caller_session_id=None)

    assert "ERROR: CALLER_SESSION_REQUIRED" in result


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
