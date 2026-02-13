"""Integration tests for state machine workflow with dependency gating.

Tests the complete workflow:
- State transitions: pending → ready → in_progress → done (via state.json phase)
- Dependency satisfaction blocking
- Integration with resolve_slug() and next_work()
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.core.db import Db
from teleclaude.core.next_machine import (
    check_dependencies_satisfied,
    get_item_phase,
    next_work,
    resolve_slug,
    set_item_phase,
    write_dependencies,
)


@pytest.mark.asyncio
async def test_workflow_pending_to_done_with_dependencies():
    """Integration test: pending → ready → in_progress → done with dependency gating"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap with dependency chain (plain slug format)
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text(
            "# Roadmap\n\n- dep-item\nDependency item description\n\n- main-item\nMain item description\n"
        )

        # Create state.json for items
        for slug in ("dep-item", "main-item"):
            d = Path(tmpdir) / "todos" / slug
            d.mkdir(parents=True, exist_ok=True)
            (d / "state.json").write_text('{"phase": "pending"}')

        # Set up dependency: main-item depends on dep-item
        deps = {"main-item": ["dep-item"]}
        with patch("teleclaude.core.next_machine.core.Repo"):
            write_dependencies(tmpdir, deps)

        # Step 1: Verify main-item cannot be selected (dependency unsatisfied)
        slug, is_ready, desc = resolve_slug(tmpdir, slug=None, ready_only=True)
        assert slug is None  # No ready items yet

        # Step 2: Mark dep-item as ready
        set_item_phase(tmpdir, "dep-item", "pending")
        # Write dor score to make it ready
        import json

        dep_state_path = Path(tmpdir) / "todos" / "dep-item" / "state.json"
        dep_state = json.loads(dep_state_path.read_text())
        dep_state["dor"] = {"score": 8}
        dep_state_path.write_text(json.dumps(dep_state))
        assert get_item_phase(tmpdir, "dep-item") == "pending"

        # Step 3: Mark dep-item as in_progress
        set_item_phase(tmpdir, "dep-item", "in_progress")
        assert get_item_phase(tmpdir, "dep-item") == "in_progress"

        # Step 4: Mark dep-item as done
        set_item_phase(tmpdir, "dep-item", "done")
        assert get_item_phase(tmpdir, "dep-item") == "done"

        # Step 5: Verify dependency is now satisfied
        satisfied = check_dependencies_satisfied(tmpdir, "main-item", deps)
        assert satisfied is True

        # Step 6: Mark main-item as ready
        set_item_phase(tmpdir, "main-item", "pending")
        main_state_path = Path(tmpdir) / "todos" / "main-item" / "state.json"
        main_state = json.loads(main_state_path.read_text())
        main_state["dor"] = {"score": 8}
        main_state_path.write_text(json.dumps(main_state))
        assert get_item_phase(tmpdir, "main-item") == "pending"

        # Step 7: Verify main-item is now selectable with ready_only
        slug, is_ready, desc = resolve_slug(tmpdir, slug=None, ready_only=True)
        assert slug == "main-item"
        assert is_ready is True


@pytest.mark.asyncio
async def test_next_work_dependency_blocking():
    """Integration test: next_work respects dependency blocking across full workflow"""
    db = MagicMock(spec=Db)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap (plain slug format)
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text(
            "# Roadmap\n\n"
            "- foundation\nFoundation work\n\n"
            "- blocked-feature\nBlocked by foundation\n\n"
            "- independent-feature\nNo dependencies\n"
        )

        # Create state.json for items
        states = {
            "foundation": '{"phase": "pending"}',
            "blocked-feature": '{"phase": "pending", "dor": {"score": 8}}',
            "independent-feature": '{"phase": "pending", "dor": {"score": 8}}',
        }
        for slug, state in states.items():
            d = Path(tmpdir) / "todos" / slug
            d.mkdir(parents=True, exist_ok=True)
            (d / "state.json").write_text(state)

        # Set up dependency: blocked-feature depends on foundation
        deps = {"blocked-feature": ["foundation"], "independent-feature": []}
        with patch("teleclaude.core.next_machine.core.Repo"):
            write_dependencies(tmpdir, deps)

        # Create required files for independent-feature
        item_dir = Path(tmpdir) / "todos" / "independent-feature"
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.json").write_text(
            '{"phase": "pending", "dor": {"score": 8}, "build": "pending", "review": "pending"}'
        )

        # Step 1: next_work should select independent-feature (no dependencies)
        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
        ):
            result = await next_work(db, slug=None, cwd=tmpdir)

        assert "independent-feature" in result
        assert "blocked-feature" not in result

        # Step 2: Try to explicitly work on blocked-feature (should be rejected)
        result = await next_work(db, slug="blocked-feature", cwd=tmpdir)
        assert "ERROR:" in result
        assert "DEPS_UNSATISFIED" in result

        # Step 3: Complete foundation item via state.json phase
        set_item_phase(tmpdir, "foundation", "done")

        # Step 4: Create required files for blocked-feature
        blocked_dir = Path(tmpdir) / "todos" / "blocked-feature"
        (blocked_dir / "requirements.md").write_text("# Requirements\n")
        (blocked_dir / "implementation-plan.md").write_text("# Plan\n")
        (blocked_dir / "state.json").write_text(
            '{"phase": "pending", "dor": {"score": 8}, "build": "pending", "review": "pending"}'
        )

        # Step 5: Now next_work can select blocked-feature (dependency satisfied)
        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
        ):
            result = await next_work(db, slug="blocked-feature", cwd=tmpdir)

        # Should no longer be blocked - verify no errors
        assert "ERROR:" not in result
        assert "DEPS_UNSATISFIED" not in result


@pytest.mark.asyncio
async def test_removed_dependency_satisfaction():
    """Integration test: Dependencies removed from roadmap are considered satisfied"""
    db = MagicMock(spec=Db)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap with an item that depends on an archived item
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Roadmap\n\n- new-feature\nNew feature\n")

        # Set up dependency on removed item
        deps = {"new-feature": ["former-foundation"]}
        with patch("teleclaude.core.next_machine.core.Repo"):
            write_dependencies(tmpdir, deps)

        # Create required files for new-feature
        item_dir = Path(tmpdir) / "todos" / "new-feature"
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.json").write_text(
            '{"phase": "pending", "dor": {"score": 8}, "build": "pending", "review": "pending"}'
        )

        # Should be able to work on new-feature (missing dependency is satisfied)
        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
        ):
            result = await next_work(db, slug="new-feature", cwd=tmpdir)

        # Should NOT be blocked
        assert "DEPS_UNSATISFIED" not in result
