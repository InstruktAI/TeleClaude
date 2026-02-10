"""Unit tests for deferral automation features."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.db import Db
from teleclaude.core.next_machine import has_pending_deferrals, next_work

# =============================================================================
# has_pending_deferrals Tests
# =============================================================================


def test_has_pending_deferrals_no_file():
    """Verify returns False when deferrals.md does not exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = has_pending_deferrals(tmpdir, "slug")
        assert result is False


def test_has_pending_deferrals_exists_unprocessed():
    """Verify returns True when deferrals.md exists and processed is False."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "slug"
        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "deferrals.md").write_text("deferrals")
        (item_dir / "state.json").write_text('{"deferrals_processed": false}')

        result = has_pending_deferrals(tmpdir, slug)
        assert result is True


def test_has_pending_deferrals_exists_processed():
    """Verify returns False when deferrals.md exists and processed is True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "slug"
        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "deferrals.md").write_text("deferrals")
        (item_dir / "state.json").write_text('{"deferrals_processed": true}')

        result = has_pending_deferrals(tmpdir, slug)
        assert result is False


def test_has_pending_deferrals_exists_no_state_key():
    """Verify returns True when deferrals.md exists and state key is missing (default False)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "slug"
        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "deferrals.md").write_text("deferrals")
        (item_dir / "state.json").write_text("{}")  # Default state has False

        result = has_pending_deferrals(tmpdir, slug)
        assert result is True


# =============================================================================
# next_work Deferral Tests
# =============================================================================


@pytest.mark.asyncio
async def test_next_work_dispatches_defer():
    """Verify next_work dispatches next-defer when pending deferrals exist."""
    db = MagicMock(spec=Db)
    slug = "defer-item"

    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup roadmap
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text(f"# Roadmap\n\n- [.] {slug}\n")

        # Setup item files
        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Req")
        (item_dir / "implementation-plan.md").write_text("# Plan")

        # Setup worktree state (Build complete, Review approved, Deferrals pending)
        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.json").write_text(
            '{"build": "complete", "review": "approved", "deferrals_processed": false}'
        )
        (state_dir / "deferrals.md").write_text("deferrals")

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch(
                "teleclaude.core.next_machine.core.get_available_agent",
                new=AsyncMock(return_value=("claude", "med")),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        assert 'command="/next-defer"' in result
        assert f'subfolder="trees/{slug}"' in result


@pytest.mark.asyncio
async def test_next_work_skips_defer_if_processed():
    """Verify next_work skips next-defer (goes to finalize) when deferrals processed."""
    db = MagicMock(spec=Db)
    slug = "processed-item"

    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup roadmap
        roadmap_path = Path(tmpdir) / "todos" / "roadmap.md"
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text(f"# Roadmap\n\n- [.] {slug}\n")

        # Setup item files
        item_dir = Path(tmpdir) / "todos" / slug
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "requirements.md").write_text("# Req")
        (item_dir / "implementation-plan.md").write_text("# Plan")

        # Setup worktree state (Build complete, Review approved, Deferrals PROCESSED)
        state_dir = Path(tmpdir) / "trees" / slug / "todos" / slug
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.json").write_text(
            '{"build": "complete", "review": "approved", "deferrals_processed": true}'
        )
        (state_dir / "deferrals.md").write_text("deferrals")

        with (
            patch("teleclaude.core.next_machine.core.Repo"),
            patch("teleclaude.core.next_machine.core.has_uncommitted_changes", return_value=False),
            patch("teleclaude.core.next_machine.core._prepare_worktree"),
            patch(
                "teleclaude.core.next_machine.core.get_available_agent",
                new=AsyncMock(return_value=("claude", "med")),
            ),
        ):
            result = await next_work(db, slug=slug, cwd=tmpdir)

        # Should go to finalize
        assert 'command="/next-finalize"' in result
