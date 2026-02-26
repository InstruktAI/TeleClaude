"""Regression test: explicit bug start should work from worktree cwd."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.db import Db
from teleclaude.core.next_machine import next_work


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_next_work_explicit_bug_slug_with_worktree_cwd_skips_dor_gate(tmp_path: Path) -> None:
    """Bug start should work when cwd points at trees/{slug} worktree."""
    db = MagicMock(spec=Db)
    slug = "fix-bug"

    # Create a real git repo + worktree so cwd normalization can resolve
    # project root from a worktree path.
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "worktree", "add", f"trees/{slug}", "-b", slug],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    todo_dir = tmp_path / "todos" / slug
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "bug.md").write_text("# Bug\n", encoding="utf-8")
    (todo_dir / "state.yaml").write_text('{"build": "pending", "review": "pending", "dor": null}', encoding="utf-8")

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
