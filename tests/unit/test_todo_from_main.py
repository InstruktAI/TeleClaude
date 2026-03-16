"""Tests for teleclaude.todo_scaffold.create_from_main_skeleton."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Patch targets — these are lazy-imported inside create_from_main_skeleton
_WT = "teleclaude.core.next_machine.worktrees"
_SI = "teleclaude.core.next_machine.state_io"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo_ns(
    *,
    branch: str = "main",
    status: str = " M src/app.py\n?? src/new.py",
    diff_stat: str = " src/app.py | 10 +++++-----\n 1 file changed",
) -> SimpleNamespace:
    """Build a SimpleNamespace that mimics a GitPython Repo for tests."""

    def update_environment(**kwargs: str) -> dict[str, str]:
        return {}

    git = SimpleNamespace(
        status=MagicMock(return_value=status),
        diff=MagicMock(return_value=diff_stat),
        show=MagicMock(side_effect=lambda ref: f"clean-content-of-{ref}"),
        reset=MagicMock(),
        update_environment=update_environment,
    )
    active_branch = SimpleNamespace(name=branch)
    return SimpleNamespace(git=git, active_branch=active_branch)


def _setup_project(tmp_path: Path) -> Path:
    """Create minimal project structure with dirty files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("modified content")
    (tmp_path / "src" / "new.py").write_text("new file content")
    (tmp_path / "todos").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateFromMainSkeleton:
    """Tests for the from-main entry ramp."""

    def test_rejects_non_main_branch(self, tmp_path: Path) -> None:
        """Must be on main branch."""
        from teleclaude.todo_scaffold import create_from_main_skeleton

        repo = _make_repo_ns(branch="feature-x")

        with (
            patch("git.Repo", return_value=repo),
            pytest.raises(ValueError, match="from-main requires being on the main branch"),
        ):
            create_from_main_skeleton(str(tmp_path), "test-slug")

    def test_rejects_clean_working_tree(self, tmp_path: Path) -> None:
        """Must have uncommitted changes."""
        from teleclaude.todo_scaffold import create_from_main_skeleton

        repo = _make_repo_ns(status="")

        with (
            patch("git.Repo", return_value=repo),
            pytest.raises(ValueError, match="No uncommitted changes"),
        ):
            create_from_main_skeleton(str(tmp_path), "test-slug")

    def test_happy_path_creates_worktree_and_cleans_main(self, tmp_path: Path) -> None:
        """Full happy path: scaffold, worktree, transfer, clean, state."""
        from teleclaude.todo_scaffold import create_from_main_skeleton

        project = _setup_project(tmp_path)
        worktree_path = project / "trees" / "test-slug"
        worktree_path.mkdir(parents=True)
        (worktree_path / "src").mkdir(parents=True)

        repo = _make_repo_ns()

        with (
            patch("git.Repo", return_value=repo),
            patch(f"{_WT}._ensure_todo_on_remote_main", return_value=(True, "committed_and_pushed")),
            patch(f"{_WT}._create_or_attach_worktree", return_value=True),
            patch(
                f"{_WT}._decide_worktree_prep",
                return_value=SimpleNamespace(should_prepare=False, inputs_digest="x"),
            ),
            patch(f"{_SI}.mark_ready") as mock_ready,
            patch(f"{_SI}.mark_phase") as mock_phase,
        ):
            output = create_from_main_skeleton(str(project), "test-slug", description="Test changes")

        # Verify output
        assert "Todo created: test-slug" in output
        assert "trees/test-slug/" in output
        assert "/next-work" in output

        # Verify todo scaffold was created
        todo_dir = project / "todos" / "test-slug"
        assert todo_dir.exists()
        assert (todo_dir / "requirements.md").exists()
        assert (todo_dir / "implementation-plan.md").exists()
        assert (todo_dir / "state.yaml").exists()

        requirements = (todo_dir / "requirements.md").read_text(encoding="utf-8")
        implementation_plan = (todo_dir / "implementation-plan.md").read_text(encoding="utf-8")
        quality_checklist = (todo_dir / "quality-checklist.md").read_text(encoding="utf-8")
        demo = (todo_dir / "demo.md").read_text(encoding="utf-8")

        assert requirements.startswith("<!-- from-main:")
        assert "Test changes" in requirements
        assert implementation_plan.startswith("<!-- from-main:")
        assert quality_checklist.startswith("<!-- from-main:")
        assert demo.startswith("<!-- no-demo: from-main")

        # Verify files were transferred to worktree
        assert (worktree_path / "src" / "app.py").exists()
        assert (worktree_path / "src" / "new.py").exists()

        # Verify main was cleaned — modified files restored from HEAD
        repo.git.show.assert_any_call("HEAD:src/app.py")

        # Verify untracked file removed from main
        assert not (project / "src" / "new.py").exists()

        # Verify state was set for review
        mock_ready.assert_called_once()
        mock_phase.assert_called_once_with(str(worktree_path), "test-slug", "build", "complete")

    def test_deleted_files_removed_from_worktree(self, tmp_path: Path) -> None:
        """Deleted files on main should be removed from the worktree."""
        from teleclaude.todo_scaffold import create_from_main_skeleton

        project = _setup_project(tmp_path)
        worktree_path = project / "trees" / "del-slug"
        worktree_path.mkdir(parents=True)
        # File exists in worktree (from origin/main) but deleted on main
        (worktree_path / "removed.py").write_text("to be deleted")

        repo = _make_repo_ns(status=" D removed.py")

        with (
            patch("git.Repo", return_value=repo),
            patch(f"{_WT}._ensure_todo_on_remote_main", return_value=(True, "committed_and_pushed")),
            patch(f"{_WT}._create_or_attach_worktree", return_value=True),
            patch(
                f"{_WT}._decide_worktree_prep",
                return_value=SimpleNamespace(should_prepare=False, inputs_digest="x"),
            ),
            patch(f"{_SI}.mark_ready"),
            patch(f"{_SI}.mark_phase"),
        ):
            create_from_main_skeleton(str(project), "del-slug")

        assert not (worktree_path / "removed.py").exists()

    def test_push_failure_raises_runtime_error(self, tmp_path: Path) -> None:
        """If scaffold push fails, raise RuntimeError."""
        from teleclaude.todo_scaffold import create_from_main_skeleton

        project = _setup_project(tmp_path)
        repo = _make_repo_ns()

        with (
            patch("git.Repo", return_value=repo),
            patch(f"{_WT}._ensure_todo_on_remote_main", return_value=(False, "push_deferred")),
            pytest.raises(RuntimeError, match="push_deferred"),
        ):
            create_from_main_skeleton(str(project), "push-fail")

    def test_description_defaults_to_see_diff(self, tmp_path: Path) -> None:
        """Without --description, requirements.md shows default text."""
        from teleclaude.todo_scaffold import create_from_main_skeleton

        project = _setup_project(tmp_path)
        worktree_path = project / "trees" / "no-desc"
        worktree_path.mkdir(parents=True)
        (worktree_path / "src").mkdir(parents=True)
        repo = _make_repo_ns()

        with (
            patch("git.Repo", return_value=repo),
            patch(f"{_WT}._ensure_todo_on_remote_main", return_value=(True, "committed_and_pushed")),
            patch(f"{_WT}._create_or_attach_worktree", return_value=True),
            patch(
                f"{_WT}._decide_worktree_prep",
                return_value=SimpleNamespace(should_prepare=False, inputs_digest="x"),
            ),
            patch(f"{_SI}.mark_ready"),
            patch(f"{_SI}.mark_phase"),
        ):
            create_from_main_skeleton(str(project), "no-desc")

        req_content = (project / "todos" / "no-desc" / "requirements.md").read_text()
        assert "See diff for details." in req_content

    def test_paths_scope_transfer_and_cleanup_to_requested_files(self, tmp_path: Path) -> None:
        """When --paths is used, only matching files should move into the worktree."""
        from teleclaude.todo_scaffold import create_from_main_skeleton

        project = _setup_project(tmp_path)
        (project / "docs").mkdir()
        (project / "docs" / "guide.md").write_text("modified guide", encoding="utf-8")
        (project / "docs" / "new.md").write_text("new doc", encoding="utf-8")

        worktree_path = project / "trees" / "scoped-slug"
        worktree_path.mkdir(parents=True)
        (worktree_path / "src").mkdir(parents=True)
        (worktree_path / "docs").mkdir(parents=True)

        repo = _make_repo_ns(status=" M src/app.py\n M docs/guide.md\n?? src/new.py\n?? docs/new.md")

        with (
            patch("git.Repo", return_value=repo),
            patch(f"{_WT}._ensure_todo_on_remote_main", return_value=(True, "committed_and_pushed")),
            patch(f"{_WT}._create_or_attach_worktree", return_value=True),
            patch(
                f"{_WT}._decide_worktree_prep",
                return_value=SimpleNamespace(should_prepare=False, inputs_digest="x"),
            ),
            patch(f"{_SI}.mark_ready"),
            patch(f"{_SI}.mark_phase"),
        ):
            create_from_main_skeleton(str(project), "scoped-slug", paths=["src"])

        assert (worktree_path / "src" / "app.py").exists()
        assert (worktree_path / "src" / "new.py").exists()
        assert not (worktree_path / "docs" / "guide.md").exists()
        assert not (worktree_path / "docs" / "new.md").exists()
        assert not (project / "src" / "new.py").exists()
        assert (project / "docs" / "guide.md").read_text(encoding="utf-8") == "modified guide"
        assert (project / "docs" / "new.md").read_text(encoding="utf-8") == "new doc"

    def test_paths_requires_at_least_one_matching_change(self, tmp_path: Path) -> None:
        """--paths should fail fast when no dirty files match the requested scope."""
        from teleclaude.todo_scaffold import create_from_main_skeleton

        project = _setup_project(tmp_path)
        repo = _make_repo_ns(status=" M src/app.py\n?? src/new.py")

        with (
            patch("git.Repo", return_value=repo),
            pytest.raises(ValueError, match="No matching uncommitted changes"),
        ):
            create_from_main_skeleton(str(project), "missing-paths", paths=["docs"])
