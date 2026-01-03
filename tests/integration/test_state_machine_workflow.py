"""Integration tests for state machine workflow with dependency gating.

Tests the complete workflow:
- State transitions: [ ] → [.] → [>] → [x]
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
    next_work,
    resolve_slug,
    update_roadmap_state,
    write_dependencies,
)


@pytest.mark.asyncio
async def test_workflow_pending_to_archived_with_dependencies():
    """Integration test: [ ] → [.] → [>] → archived with dependency gating"""
    db = MagicMock(spec=Db)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap with dependency chain
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text(
            "# Roadmap\n\n- [ ] dep-item\nDependency item description\n\n- [ ] main-item\nMain item description\n"
        )

        # Set up dependency: main-item depends on dep-item
        deps = {"main-item": ["dep-item"]}
        with patch("teleclaude.core.next_machine.Repo"):
            write_dependencies(tmpdir, deps)

        # Step 1: Verify main-item cannot be marked ready (dependency unsatisfied)
        slug, is_ready, desc = resolve_slug(tmpdir, slug=None, ready_only=True)
        assert slug is None  # No ready items yet

        # Step 2: Mark dep-item as ready [.]
        with patch("teleclaude.core.next_machine.Repo"):
            result = update_roadmap_state(tmpdir, "dep-item", ".")
        assert result is True

        # Step 3: Mark dep-item as in-progress [>]
        with patch("teleclaude.core.next_machine.Repo"):
            result = update_roadmap_state(tmpdir, "dep-item", ">")
        assert result is True

        # Step 4: Mark dep-item as completed [x]
        with patch("teleclaude.core.next_machine.Repo"):
            result = update_roadmap_state(tmpdir, "dep-item", "x")
        assert result is True

        # Step 5: Verify dependency is now satisfied
        satisfied = check_dependencies_satisfied(tmpdir, "main-item", deps)
        assert satisfied is True

        # Step 6: Mark main-item as ready [.]
        with patch("teleclaude.core.next_machine.Repo"):
            result = update_roadmap_state(tmpdir, "main-item", ".")
        assert result is True

        # Step 7: Verify main-item is now selectable with ready_only
        slug, is_ready, desc = resolve_slug(tmpdir, slug=None, ready_only=True)
        assert slug == "main-item"
        assert is_ready is True

        # Verify roadmap state transitions occurred correctly
        content = roadmap_path.read_text()
        assert "- [x] dep-item" in content
        assert "- [.] main-item" in content


@pytest.mark.asyncio
async def test_next_work_dependency_blocking():
    """Integration test: next_work respects dependency blocking across full workflow"""
    db = MagicMock(spec=Db)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap with multiple items and dependencies
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text(
            "# Roadmap\n\n"
            "- [ ] foundation\nFoundation work\n\n"
            "- [.] blocked-feature\nBlocked by foundation\n\n"
            "- [.] independent-feature\nNo dependencies\n"
        )

        # Set up dependency: blocked-feature depends on foundation
        deps = {"blocked-feature": ["foundation"], "independent-feature": []}
        with patch("teleclaude.core.next_machine.Repo"):
            write_dependencies(tmpdir, deps)

        # Create required files for independent-feature
        item_dir = Path(tmpdir) / "todos" / "independent-feature"
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.json").write_text('{"build": "pending", "review": "pending"}')

        # Step 1: next_work should select independent-feature (no dependencies)
        with patch("teleclaude.core.next_machine.Repo"):
            result = await next_work(db, slug=None, cwd=tmpdir)

        assert "independent-feature" in result
        assert "blocked-feature" not in result

        # Step 2: Try to explicitly work on blocked-feature (should be rejected)
        result = await next_work(db, slug="blocked-feature", cwd=tmpdir)
        assert "ERROR:" in result
        assert "DEPS_UNSATISFIED" in result

        # Step 3: Complete foundation item
        with patch("teleclaude.core.next_machine.Repo"):
            update_roadmap_state(tmpdir, "foundation", ".")
            update_roadmap_state(tmpdir, "foundation", ">")
            update_roadmap_state(tmpdir, "foundation", "x")

        # Step 4: Create required files for blocked-feature
        blocked_dir = Path(tmpdir) / "todos" / "blocked-feature"
        blocked_dir.mkdir(parents=True, exist_ok=True)
        (blocked_dir / "requirements.md").write_text("# Requirements\n")
        (blocked_dir / "implementation-plan.md").write_text("# Plan\n")
        (blocked_dir / "state.json").write_text('{"build": "pending", "review": "pending"}')

        # Step 5: Now next_work can select blocked-feature (dependency satisfied)
        with patch("teleclaude.core.next_machine.Repo"):
            result = await next_work(db, slug="blocked-feature", cwd=tmpdir)

        # Should no longer be blocked - verify no errors
        assert "ERROR:" not in result
        assert "DEPS_UNSATISFIED" not in result


@pytest.mark.asyncio
async def test_archived_dependency_satisfaction():
    """Integration test: Dependencies in done/ directory are considered satisfied"""
    db = MagicMock(spec=Db)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create roadmap with an item that depends on an archived item
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Roadmap\n\n- [.] new-feature\nNew feature\n")

        # Set up dependency on archived item
        deps = {"new-feature": ["archived-foundation"]}
        with patch("teleclaude.core.next_machine.Repo"):
            write_dependencies(tmpdir, deps)

        # Simulate archived dependency in done/ directory
        done_dir = Path(tmpdir) / "done" / "001-archived-foundation"
        done_dir.mkdir(parents=True, exist_ok=True)

        # Create required files for new-feature
        item_dir = Path(tmpdir) / "todos" / "new-feature"
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Requirements\n")
        (item_dir / "implementation-plan.md").write_text("# Plan\n")
        (item_dir / "state.json").write_text('{"build": "pending", "review": "pending"}')

        # Should be able to work on new-feature (archived dependency is satisfied)
        with patch("teleclaude.core.next_machine.Repo"):
            result = await next_work(db, slug="new-feature", cwd=tmpdir)

        # Should NOT be blocked
        assert "DEPS_UNSATISFIED" not in result
