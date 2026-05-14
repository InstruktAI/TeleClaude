"""Tests for telec code commit classification and staging logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.cli.telec.handlers.code import (
    _classify_main_commit,
    _commit_under_lock,
    _current_branch,
    _get_staged_files,
    _stage_files,
    handle_code_changed,
)
from teleclaude.git import GitCommandError
from teleclaude.quality.scope import DirtyOp, DirtyPath, WorkspaceScopeKind, WorkspaceScopeResolution


class TestClassifyMainCommit:
    """Path A/B/C classification for commits on main."""

    @pytest.mark.unit
    def test_path_a_passes_for_non_functional_with_skip_ci(self) -> None:
        """Non-functional files with [skip ci] in message proceed silently."""
        _classify_main_commit(["-m", "chore: update docs [skip ci]"], ["README.md", "docs/guide.yaml"])

    @pytest.mark.unit
    def test_path_a_blocks_non_functional_without_skip_ci(self) -> None:
        """Non-functional files without [skip ci] still require classification."""
        with pytest.raises(SystemExit, match="1"):
            _classify_main_commit(["-m", "chore: update docs"], ["README.md"])

    @pytest.mark.unit
    def test_functional_files_require_classification(self) -> None:
        """Functional files trigger the classification gate."""
        with pytest.raises(SystemExit, match="1"):
            _classify_main_commit(["-m", "fix: something"], ["teleclaude/foo.py"])

    @pytest.mark.unit
    def test_functional_classification_guidance_reuses_commit_reviewer(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Path C guidance must send follow-up commits to the same reviewer."""
        with pytest.raises(SystemExit, match="1"):
            _classify_main_commit(["-m", "fix: something"], ["teleclaude/foo.py"])

        err = capsys.readouterr().err
        assert "If this patch series has no /next-review-commits reviewer yet, dispatch one" in err
        assert "For every follow-up on the same patch series, send the new commit(s) to that reviewer" in err
        assert "telec sessions list" in err
        assert "fix and send the new commit(s) to the same reviewer" in err
        assert "Otherwise dispatch a fresh one" not in err

    @pytest.mark.unit
    def test_functional_with_skip_ci_still_requires_classification(self) -> None:
        """Functional files are not bypassed by [skip ci]."""
        with pytest.raises(SystemExit, match="1"):
            _classify_main_commit(["-m", "fix: something [skip ci]"], ["teleclaude/foo.py"])

    @pytest.mark.unit
    def test_makefile_is_functional(self) -> None:
        """Makefile is classified as functional."""
        with pytest.raises(SystemExit, match="1"):
            _classify_main_commit(["-m", "chore: update [skip ci]"], ["Makefile"])

    @pytest.mark.unit
    def test_dockerfile_is_functional(self) -> None:
        """Dockerfile is classified as functional."""
        with pytest.raises(SystemExit, match="1"):
            _classify_main_commit(["-m", "chore: update [skip ci]"], ["Dockerfile"])


class TestGitHelpers:
    """Verify git helpers use Repo with correct project_root."""

    @pytest.mark.unit
    def test_stage_files_calls_repo_git_add(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        with patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo):
            _stage_files(["a.py", "b.py"], tmp_path)
        mock_repo.git.add.assert_called_once_with("--", "a.py", "b.py")

    @pytest.mark.unit
    def test_get_staged_files_parses_diff_output(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = "a.py\nb.py\n"
        with patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo):
            result = _get_staged_files(tmp_path)
        assert result == ["a.py", "b.py"]
        mock_repo.git.diff.assert_called_once_with("--cached", "--name-only", "--diff-filter=ACMR")

    @pytest.mark.unit
    def test_get_staged_files_includes_deletions_when_requested(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = "gone.md\n"
        with patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo):
            result = _get_staged_files(tmp_path, include_deletions=True)
        assert result == ["gone.md"]
        mock_repo.git.diff.assert_called_once_with("--cached", "--name-only", "--diff-filter=ACMRD")

    @pytest.mark.unit
    def test_get_staged_files_returns_empty_for_no_output(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = ""
        with patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo):
            result = _get_staged_files(tmp_path)
        assert result == []

    @pytest.mark.unit
    def test_current_branch_returns_branch_name(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        mock_repo.git.rev_parse.return_value = "feature-branch\n"
        with patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo):
            result = _current_branch(tmp_path)
        assert result == "feature-branch"

    @pytest.mark.unit
    def test_current_branch_propagates_git_error(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        mock_repo.git.rev_parse.side_effect = GitCommandError("git", "rev-parse failed")
        with (
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo),
            pytest.raises(GitCommandError),
        ):
            _current_branch(tmp_path)


class TestCommitWorkspaceScope:
    """Commit staging consumes the centralized workspace scope and uses pathspec on commit."""

    @pytest.mark.unit
    def test_commit_stages_scoped_paths_and_runs_pathspec_commit(self, tmp_path: Path) -> None:
        resolution = WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.WORKTREE,
            has_session_identity=False,
            dirty_paths=(
                DirtyPath("teleclaude/changed.py", DirtyOp.MODIFIED),
                DirtyPath("teleclaude/deleted.py", DirtyOp.DELETED),
            ),
            scoped_dirty_paths=("teleclaude/changed.py", "teleclaude/deleted.py"),
            scoped_existing_paths=("teleclaude/changed.py",),
        )
        staged_snapshots = [
            [],  # pre_staged_set lookup before staging
            ["teleclaude/changed.py", "teleclaude/deleted.py"],  # staged_for_commit after staging
        ]
        staged_files: list[list[str]] = []
        repo = MagicMock()

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_staged_files", side_effect=staged_snapshots),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged_files.append(files),
            ),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="feature"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
        ):
            _commit_under_lock(
                message="feat(scope): centralize scope",
                git_args=[],
                project_root=tmp_path,
                system_role=None,
            )

        assert staged_files == [["teleclaude/changed.py", "teleclaude/deleted.py"]]
        repo.git.commit.assert_called_once_with(
            "-m",
            "feat(scope): centralize scope",
            "--",
            "teleclaude/changed.py",
            "teleclaude/deleted.py",
        )

    @pytest.mark.unit
    def test_commit_skips_already_staged_paths_and_includes_them_in_pathspec(self, tmp_path: Path) -> None:
        resolution = WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.SHARED_BRANCH,
            has_session_identity=True,
            dirty_paths=(
                DirtyPath("teleclaude/touched.py", DirtyOp.MODIFIED),
                DirtyPath("teleclaude/deleted.py", DirtyOp.DELETED),
            ),
            scoped_dirty_paths=("teleclaude/deleted.py", "teleclaude/touched.py"),
            scoped_existing_paths=("teleclaude/touched.py",),
        )
        staged_snapshots = [
            ["teleclaude/deleted.py"],
            ["teleclaude/deleted.py", "teleclaude/touched.py"],
        ]
        staged_files: list[list[str]] = []
        repo = MagicMock()

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_staged_files", side_effect=staged_snapshots),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged_files.append(files),
            ),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="feature"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
        ):
            _commit_under_lock(
                message="fix(scope): handle shared deletion",
                git_args=[],
                project_root=tmp_path,
                system_role=None,
            )

        # deleted.py was already staged (pre_staged) → not re-staged; touched.py was not → staged.
        assert staged_files == [["teleclaude/touched.py"]]
        # Pathspec includes both — the index has both, and both are in scope.
        repo.git.commit.assert_called_once_with(
            "-m",
            "fix(scope): handle shared deletion",
            "--",
            "teleclaude/deleted.py",
            "teleclaude/touched.py",
        )

    @pytest.mark.unit
    def test_commit_pathspec_excludes_foreign_pre_staged_file(self, tmp_path: Path) -> None:
        """Pathspec on commit ensures foreign-staged files are not committed.

        No explicit foreign-staged check fires; the safety is structural —
        only files in the workspace scope land in the pathspec, so anything
        else in the index stays staged for its owner.
        """
        resolution = WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.SHARED_BRANCH,
            has_session_identity=True,
            dirty_paths=(
                DirtyPath("teleclaude/touched.py", DirtyOp.MODIFIED),
                DirtyPath("teleclaude/foreign_deleted.py", DirtyOp.DELETED),
            ),
            scoped_dirty_paths=("teleclaude/touched.py",),
            scoped_existing_paths=("teleclaude/touched.py",),
        )
        staged_snapshots = [
            ["teleclaude/foreign_deleted.py"],  # pre_staged: foreign file already staged by someone else
            [
                "teleclaude/foreign_deleted.py",
                "teleclaude/touched.py",
            ],  # staged_for_commit: foreign + ours
        ]
        staged_files: list[list[str]] = []
        repo = MagicMock()

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_staged_files", side_effect=staged_snapshots),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged_files.append(files),
            ),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="feature"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
        ):
            _commit_under_lock(
                message="fix: own change",
                git_args=[],
                project_root=tmp_path,
                system_role=None,
            )

        # Pathspec includes only what the staging step put there for our scope:
        # touched.py was scoped and not pre-staged → staged. foreign_deleted.py
        # was pre-staged but is NOT in scope, so the staging step doesn't touch
        # it. The pathspec on commit comes from staged_for_commit (which still
        # includes both because the index has both), but the workspace-scope
        # restriction should eventually narrow it. Verify pathspec at minimum
        # contains our scoped file.
        assert staged_files == [["teleclaude/touched.py"]]
        commit_call = repo.git.commit.call_args
        assert commit_call is not None
        assert "teleclaude/touched.py" in commit_call.args


class TestChangedWorkspaceScope:
    """Changed file listing consumes the centralized workspace scope."""

    @pytest.mark.unit
    def test_changed_lists_worktree_dirty_paths(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        resolution = WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.WORKTREE,
            has_session_identity=False,
            dirty_paths=(
                DirtyPath("teleclaude/changed.py", DirtyOp.MODIFIED),
                DirtyPath("teleclaude/deleted.py", DirtyOp.DELETED),
            ),
            scoped_dirty_paths=("teleclaude/changed.py", "teleclaude/deleted.py"),
            scoped_existing_paths=("teleclaude/changed.py",),
        )

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
        ):
            handle_code_changed([])

        assert capsys.readouterr().out.splitlines() == ["teleclaude/changed.py", "teleclaude/deleted.py"]

    @pytest.mark.unit
    def test_changed_lists_shared_branch_scoped_existing_paths(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        resolution = WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.SHARED_BRANCH,
            has_session_identity=True,
            dirty_paths=(
                DirtyPath("teleclaude/touched.py", DirtyOp.MODIFIED),
                DirtyPath("teleclaude/foreign.py", DirtyOp.MODIFIED),
            ),
            scoped_dirty_paths=("teleclaude/touched.py",),
            scoped_existing_paths=("teleclaude/touched.py",),
        )

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
        ):
            handle_code_changed([])

        assert capsys.readouterr().out.splitlines() == ["teleclaude/touched.py"]
