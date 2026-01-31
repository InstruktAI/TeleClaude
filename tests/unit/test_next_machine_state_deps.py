"""Unit tests for state machine refinement features.

Tests for:
- update_roadmap_state() function
- resolve_slug() with ready-only mode
- Dependency tracking and satisfaction logic
- teleclaude__set_dependencies() validation
- Circular dependency detection
- next_work() without bug check
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.db import Db
from teleclaude.core.next_machine import (
    check_dependencies_satisfied,
    detect_circular_dependency,
    next_work,
    read_dependencies,
    resolve_slug,
    update_roadmap_state,
    write_dependencies,
)

# =============================================================================
# update_roadmap_state Tests
# =============================================================================


def test_update_roadmap_state_pending_to_ready():
    """Verify state transition from [ ] to [.]"""
    with tempfile.TemporaryDirectory() as tmpdir:
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Roadmap\n\n- [ ] test-item\nDescription here\n")

        # Mock git operations
        with patch("teleclaude.core.next_machine.core.Repo"):
            result = update_roadmap_state(tmpdir, "test-item", ".")

        assert result is True
        content = roadmap_path.read_text()
        assert "- [.] test-item" in content


def test_update_roadmap_state_ready_to_in_progress():
    """Verify state transition from [.] to [>]"""
    with tempfile.TemporaryDirectory() as tmpdir:
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Roadmap\n\n- [.] test-item\nDescription here\n")

        with patch("teleclaude.core.next_machine.core.Repo"):
            result = update_roadmap_state(tmpdir, "test-item", ">")

        assert result is True
        content = roadmap_path.read_text()
        assert "- [>] test-item" in content


def test_update_roadmap_state_slug_not_found():
    """Verify function returns False when slug doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Roadmap\n\n- [ ] other-item\n")

        with patch("teleclaude.core.next_machine.core.Repo"):
            result = update_roadmap_state(tmpdir, "nonexistent", ".")

        assert result is False


# =============================================================================
# Dependency Tracking Tests
# =============================================================================


def test_read_dependencies_missing_file():
    """Verify read_dependencies returns empty dict when file doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        deps = read_dependencies(tmpdir)
        assert deps == {}


def test_write_and_read_dependencies():
    """Verify writing and reading dependencies works correctly"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Ensure todos directory exists
        todos_dir = Path(tmpdir) / "todos"
        todos_dir.mkdir(parents=True, exist_ok=True)

        test_deps = {"item-a": ["item-b", "item-c"], "item-d": ["item-a"]}

        # Mock git operations
        with patch("teleclaude.core.next_machine.core.Repo"):
            write_dependencies(tmpdir, test_deps)

        deps = read_dependencies(tmpdir)

        assert deps == test_deps

        # Verify file format
        deps_path = Path(tmpdir) / "todos" / "dependencies.json"
        content = deps_path.read_text()
        parsed = json.loads(content)
        assert parsed == test_deps


def test_check_dependencies_satisfied_no_deps():
    """Verify item with no dependencies is always satisfied"""
    with tempfile.TemporaryDirectory() as tmpdir:
        deps = {}
        result = check_dependencies_satisfied(tmpdir, "test-item", deps)
        assert result is True


def test_check_dependencies_satisfied_all_complete():
    """Verify dependencies are satisfied when all are completed"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap with completed dependencies
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Roadmap\n\n- [x] dep-a\n- [x] dep-b\n- [.] test-item\n")

        deps = {"test-item": ["dep-a", "dep-b"]}
        result = check_dependencies_satisfied(tmpdir, "test-item", deps)
        assert result is True


def test_check_dependencies_satisfied_incomplete():
    """Verify dependencies are not satisfied when some are incomplete"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap with one incomplete dependency
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Roadmap\n\n- [x] dep-a\n- [ ] dep-b\n- [.] test-item\n")

        deps = {"test-item": ["dep-a", "dep-b"]}
        result = check_dependencies_satisfied(tmpdir, "test-item", deps)
        assert result is False


def test_check_dependencies_satisfied_removed():
    """Verify dependencies missing from roadmap are satisfied"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap without the dependency (assumed completed/removed)
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Roadmap\n\n- [.] test-item\n")

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

        # Create roadmap with ready item
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.write_text("# Roadmap\n\n- [.] test-item\n")

        # Create required files
        item_dir = Path(tmpdir) / "todos" / "test-item"
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.json").write_text('{"build": "pending", "review": "pending"}')

        # Mock git operations
        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
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
        # Create roadmap with ready items
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Roadmap\n\n- [ ] dep-item\n- [.] blocked-item\n- [.] ready-item\n")

        # Ensure todos directory exists
        todos_dir = Path(tmpdir) / "todos"
        todos_dir.mkdir(parents=True, exist_ok=True)

        # Set up dependencies
        deps = {"blocked-item": ["dep-item"], "ready-item": []}
        with patch("teleclaude.core.next_machine.core.Repo"):
            write_dependencies(tmpdir, deps)

        # Create required files for ready-item
        item_dir = Path(tmpdir) / "todos" / "ready-item"
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.json").write_text('{"build": "pending", "review": "pending"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
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
        # Create roadmap
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Roadmap\n\n- [ ] dep-item\n- [.] blocked-item\n")

        # Set up dependency
        deps = {"blocked-item": ["dep-item"]}
        write_dependencies(tmpdir, deps)

        result = await next_work(db, slug="blocked-item", cwd=tmpdir)

        # Should return error about unsatisfied dependencies
        assert "ERROR:" in result
        assert "DEPS_UNSATISFIED" in result


@pytest.mark.asyncio
async def test_next_work_explicit_slug_rejects_pending_items():
    """Verify explicit slug rejects [ ] (pending) items"""
    db = MagicMock(spec=Db)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap with pending item
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Roadmap\n\n- [ ] pending-item\n- [.] ready-item\n")

        result = await next_work(db, slug="pending-item", cwd=tmpdir)

        # Should return error indicating item is not ready
        assert "ERROR:" in result
        assert "ITEM_NOT_READY" in result
        assert "[ ] (pending)" in result


@pytest.mark.asyncio
async def test_next_work_review_includes_merge_base_note():
    """Verify next_work review dispatch includes merge-base guard note."""
    db = MagicMock(spec=Db)
    slug = "review-item"

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap with ready item
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text(f"# Roadmap\n\n- [.] {slug}\n")

        # Create required files in main repo
        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")

        # Create worktree state with build complete and review pending
        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.json").write_text('{"build": "complete", "review": "pending"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core.is_main_ahead", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "next-review" in result
        assert "merge-base" in result


@pytest.mark.asyncio
async def test_next_work_blocks_review_when_main_ahead():
    """Verify next_work blocks review dispatch when main is ahead."""
    db = MagicMock(spec=Db)
    slug = "review-blocked"

    with tempfile.TemporaryDirectory() as tmpdir:
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text(f"# Roadmap\n\n- [.] {slug}\n")

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.json").write_text('{"build": "complete", "review": "pending"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.ensure_worktree", return_value=False),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core.is_main_ahead", return_value=True),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert "ERROR:" in result
        assert "MAIN_AHEAD" in result


@pytest.mark.asyncio
async def test_next_work_finalize_next_call_without_slug():
    """Finalize dispatch should call next_work without slug."""
    db = MagicMock(spec=Db)
    slug = "final-item"

    with tempfile.TemporaryDirectory() as tmpdir:
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text(f"# Roadmap\n\n- [.] {slug}\n")

        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")

        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.json").write_text('{"build": "complete", "review": "approved"}')

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch("teleclaude.core.next_machine.core.is_docstrings_complete", return_value=True),
            patch("teleclaude.core.next_machine.core.is_snippets_complete", return_value=True),
            patch(
                "teleclaude.core.next_machine.core.get_available_agent",
                new=AsyncMock(return_value=("claude", "med")),
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
    """Verify ready_only=True only matches [.] items"""
    with tempfile.TemporaryDirectory() as tmpdir:
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text(
            "# Roadmap\n\n- [ ] pending-item\n- [.] ready-item\n- [>] in-progress-item\n- [x] done-item\n"
        )

        slug, is_ready, desc = resolve_slug(tmpdir, slug=None, ready_only=True)

        # Should only match the first [.] item
        assert slug == "ready-item"
        assert is_ready is True


def test_resolve_slug_ready_only_no_ready_items():
    """Verify ready_only=True returns None when no [.] items exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Roadmap\n\n- [ ] pending-item\n- [>] in-progress-item\n")

        slug, is_ready, desc = resolve_slug(tmpdir, slug=None, ready_only=True)

        assert slug is None
        assert is_ready is False


def test_resolve_slug_ready_only_skips_pending():
    """Verify ready_only=True skips [ ] items"""
    with tempfile.TemporaryDirectory() as tmpdir:
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Roadmap\n\n- [ ] pending-item\n- [.] ready-item\n")

        slug, is_ready, desc = resolve_slug(tmpdir, slug=None, ready_only=True)

        # Should skip pending and match ready
        assert slug == "ready-item"


def test_resolve_slug_ready_only_skips_in_progress():
    """Verify ready_only=True skips [>] items"""
    with tempfile.TemporaryDirectory() as tmpdir:
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Roadmap\n\n- [>] in-progress-item\n- [.] ready-item\n")

        slug, is_ready, desc = resolve_slug(tmpdir, slug=None, ready_only=True)

        # Should skip in-progress and match ready
        assert slug == "ready-item"
