"""Tests for idempotent delivery cleanup (cleanup_delivered_slug + deliver_to_delivered)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from teleclaude.core.next_machine.core import (
    cleanup_delivered_slug,
    deliver_to_delivered,
    load_delivered_slugs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_roadmap(cwd: str, slugs: list[str]) -> None:
    """Write a minimal roadmap.yaml with given slugs."""
    entries = [{"slug": s, "title": s, "status": "ready"} for s in slugs]
    path = Path(cwd) / "todos" / "roadmap.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(entries, default_flow_style=False), encoding="utf-8")


def _write_delivered(cwd: str, slugs: list[str]) -> None:
    """Write a minimal delivered.yaml with given slugs."""
    entries = [{"slug": s, "date": "2026-01-01"} for s in slugs]
    path = Path(cwd) / "todos" / "delivered.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# Delivered work items. Newest first.\n\n"
    path.write_text(header + yaml.dump(entries, default_flow_style=False), encoding="utf-8")


def _make_todo_dir(cwd: str, slug: str) -> Path:
    """Create a todo directory with a dummy file."""
    todo_dir = Path(cwd) / "todos" / slug
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "requirements.md").write_text("# Req", encoding="utf-8")
    return todo_dir


def _make_worktree_dir(cwd: str, slug: str) -> Path:
    """Create a fake worktree directory."""
    wt = Path(cwd) / "trees" / slug
    wt.mkdir(parents=True, exist_ok=True)
    (wt / ".git").write_text("gitdir: fake", encoding="utf-8")
    return wt


# ---------------------------------------------------------------------------
# deliver_to_delivered — idempotency
# ---------------------------------------------------------------------------


class TestDeliverToDelivered:
    def test_normal_delivery(self, tmp_path: Path) -> None:
        cwd = str(tmp_path)
        _write_roadmap(cwd, ["my-slug"])
        result = deliver_to_delivered(cwd, "my-slug")
        assert result is True
        assert "my-slug" in load_delivered_slugs(cwd)

    def test_already_delivered_returns_true(self, tmp_path: Path) -> None:
        cwd = str(tmp_path)
        _write_roadmap(cwd, [])
        _write_delivered(cwd, ["my-slug"])
        result = deliver_to_delivered(cwd, "my-slug")
        assert result is True

    def test_unknown_slug_returns_false(self, tmp_path: Path) -> None:
        cwd = str(tmp_path)
        _write_roadmap(cwd, ["other"])
        _write_delivered(cwd, [])
        result = deliver_to_delivered(cwd, "nonexistent")
        assert result is False


# ---------------------------------------------------------------------------
# cleanup_delivered_slug
# ---------------------------------------------------------------------------


class TestCleanupDeliveredSlug:
    @patch("teleclaude.core.next_machine.core._run_git_cmd")
    def test_full_cleanup(self, mock_git: object, tmp_path: Path) -> None:
        """Worktree + branch + todo dir all exist — all get cleaned up."""
        mock_git.return_value = (0, "", "")  # type: ignore[attr-defined]
        cwd = str(tmp_path)

        _make_worktree_dir(cwd, "my-slug")
        _make_todo_dir(cwd, "my-slug")
        _write_roadmap(cwd, [])  # empty roadmap (no deps to clean)

        cleanup_delivered_slug(cwd, "my-slug")

        # Worktree removed via git
        mock_git.assert_any_call(  # type: ignore[attr-defined]
            ["worktree", "remove", "--force", str(tmp_path / "trees" / "my-slug")],
            cwd=cwd,
            timeout=10,
        )
        # Local branch deleted
        mock_git.assert_any_call(["branch", "-D", "my-slug"], cwd=cwd)  # type: ignore[attr-defined]
        # Remote branch deleted
        mock_git.assert_any_call(  # type: ignore[attr-defined]
            ["push", "origin", "--delete", "my-slug"], cwd=cwd, timeout=5
        )
        # Todo dir removed
        assert not (tmp_path / "todos" / "my-slug").exists()

    @patch("teleclaude.core.next_machine.core._run_git_cmd")
    def test_idempotent_rerun(self, mock_git: object, tmp_path: Path) -> None:
        """Second call is all no-ops when artifacts are already gone."""
        import shutil as _shutil

        mock_git.return_value = (0, "", "")  # type: ignore[attr-defined]
        cwd = str(tmp_path)
        _write_roadmap(cwd, [])

        # First run with artifacts
        wt = _make_worktree_dir(cwd, "my-slug")
        _make_todo_dir(cwd, "my-slug")
        cleanup_delivered_slug(cwd, "my-slug")
        assert not (tmp_path / "todos" / "my-slug").exists()
        # Simulate git actually removing the worktree dir
        if wt.exists():
            _shutil.rmtree(wt)

        # Second run — no artifacts to clean
        mock_git.reset_mock()  # type: ignore[attr-defined]
        cleanup_delivered_slug(cwd, "my-slug")

        # Worktree remove not called (dir doesn't exist)
        calls = [c for c in mock_git.call_args_list if "worktree" in str(c)]  # type: ignore[attr-defined]
        assert len(calls) == 0

    @patch("teleclaude.core.next_machine.core._run_git_cmd")
    def test_partial_state(self, mock_git: object, tmp_path: Path) -> None:
        """Worktree gone, branch + todo dir remain — only those get cleaned."""
        mock_git.return_value = (0, "", "")  # type: ignore[attr-defined]
        cwd = str(tmp_path)
        _write_roadmap(cwd, [])

        # No worktree, but todo dir exists
        _make_todo_dir(cwd, "my-slug")
        cleanup_delivered_slug(cwd, "my-slug")

        # Worktree remove NOT called (dir doesn't exist)
        calls = [c for c in mock_git.call_args_list if "worktree" in str(c)]  # type: ignore[attr-defined]
        assert len(calls) == 0
        # Branch delete still called
        mock_git.assert_any_call(["branch", "-D", "my-slug"], cwd=cwd)  # type: ignore[attr-defined]
        # Todo dir removed
        assert not (tmp_path / "todos" / "my-slug").exists()

    @patch("teleclaude.core.next_machine.core._run_git_cmd")
    def test_custom_branch_name(self, mock_git: object, tmp_path: Path) -> None:
        """Branch parameter overrides slug for git operations."""
        mock_git.return_value = (0, "", "")  # type: ignore[attr-defined]
        cwd = str(tmp_path)
        _write_roadmap(cwd, [])

        cleanup_delivered_slug(cwd, "my-slug", branch="feature/custom")

        mock_git.assert_any_call(["branch", "-D", "feature/custom"], cwd=cwd)  # type: ignore[attr-defined]
        mock_git.assert_any_call(  # type: ignore[attr-defined]
            ["push", "origin", "--delete", "feature/custom"], cwd=cwd, timeout=5
        )

    @patch("teleclaude.core.next_machine.core._run_git_cmd")
    def test_skip_remote_branch(self, mock_git: object, tmp_path: Path) -> None:
        """remove_remote_branch=False skips the push --delete call."""
        mock_git.return_value = (0, "", "")  # type: ignore[attr-defined]
        cwd = str(tmp_path)
        _write_roadmap(cwd, [])

        cleanup_delivered_slug(cwd, "my-slug", remove_remote_branch=False)

        push_calls = [c for c in mock_git.call_args_list if "push" in str(c)]  # type: ignore[attr-defined]
        assert len(push_calls) == 0

    @patch("teleclaude.core.next_machine.core._run_git_cmd")
    def test_already_delivered_cleanup_still_runs(self, mock_git: object, tmp_path: Path) -> None:
        """Cleanup runs even when slug is already in delivered.yaml."""
        mock_git.return_value = (0, "", "")  # type: ignore[attr-defined]
        cwd = str(tmp_path)
        _write_roadmap(cwd, [])
        _write_delivered(cwd, ["my-slug"])
        _make_todo_dir(cwd, "my-slug")

        cleanup_delivered_slug(cwd, "my-slug")

        # Todo dir still gets cleaned
        assert not (tmp_path / "todos" / "my-slug").exists()
        # Git ops still run
        mock_git.assert_any_call(["branch", "-D", "my-slug"], cwd=cwd)  # type: ignore[attr-defined]
