"""Tests for telec code commit classification and staging logic."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.cli.telec.handlers.code import (
    _commit_under_lock,
    _current_branch,
    _dirty_paths,
    _get_staged_files,
    _get_unmerged_files,
    _get_untracked_files,
    _stage_files,
    _with_trailer,
    handle_code_add,
    handle_code_changed,
    handle_code_commit,
)
from teleclaude.git import GitCommandError
from teleclaude.quality.scope import DirtyOp, DirtyPath, WorkspaceScopeKind, WorkspaceScopeResolution

REPO_ROOT = Path(__file__).resolve().parents[5]


class TestGitHelpers:
    """Verify git helpers use Repo with correct project_root."""

    @pytest.mark.unit
    def test_stage_files_calls_repo_git_add(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        with patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo):
            _stage_files(["a.py", "b.py"], tmp_path)
        mock_repo.git.add.assert_called_once_with("--", "a.py", "b.py")

    @pytest.mark.unit
    def test_get_untracked_files_parses_ls_files_output(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        mock_repo.git.ls_files.return_value = "new1.py\nnew2.py\n"
        with patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo):
            result = _get_untracked_files(tmp_path)
        assert result == ["new1.py", "new2.py"]
        mock_repo.git.ls_files.assert_called_once_with("--others", "--exclude-standard")

    @pytest.mark.unit
    def test_get_staged_files_parses_diff_output(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = "a.py\nb.py\n"
        with patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo):
            result = _get_staged_files(tmp_path)
        assert result == ["a.py", "b.py"]
        mock_repo.git.diff.assert_called_once_with("--cached", "--name-only", "--diff-filter=ACMR")

    @pytest.mark.unit
    def test_get_unmerged_files_dedupes_across_stages(self, tmp_path: Path) -> None:
        """`git ls-files -u` emits a row per conflict stage; dedupe by path."""
        mock_repo = MagicMock()
        # Three rows for the same file (stages 1/2/3) + one row for another file.
        mock_repo.git.ls_files.return_value = (
            "100644 abc123 1\tconflicted.py\n"
            "100644 def456 2\tconflicted.py\n"
            "100644 789xyz 3\tconflicted.py\n"
            "100644 aaa000 2\tother.py\n"
        )
        with patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo):
            result = _get_unmerged_files(tmp_path)
        assert result == ["conflicted.py", "other.py"]
        mock_repo.git.ls_files.assert_called_once_with("-u")

    @pytest.mark.unit
    def test_dirty_paths_unions_staged_unstaged_and_untracked(self, tmp_path: Path) -> None:
        """_dirty_paths returns the union of every pending-change source."""
        mock_repo = MagicMock()
        # repo.git.diff is invoked twice (cached + uncached) and ls_files once.
        mock_repo.git.diff.side_effect = ["staged.py\n", "modified.py\n"]
        mock_repo.git.ls_files.return_value = "new.py\n"
        with patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo):
            result = _dirty_paths(tmp_path)
        assert result == {"staged.py", "modified.py", "new.py"}

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
    def test_untracked_in_scope_dropped_unless_pre_staged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """NEW files (untracked) in scope are NOT auto-committed. The agent must
        declare them via `telec code add` (which stages them) or `--include`.
        Without declaration: dropped from pathspec, surfaced as a reminder."""
        resolution = WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.WORKTREE,
            has_session_identity=False,
            dirty_paths=(
                DirtyPath("teleclaude/modified.py", DirtyOp.MODIFIED),
                DirtyPath("teleclaude/brand_new.py", DirtyOp.MODIFIED),
            ),
            scoped_dirty_paths=("teleclaude/modified.py", "teleclaude/brand_new.py"),
            scoped_existing_paths=("teleclaude/modified.py", "teleclaude/brand_new.py"),
        )
        staged_files: list[list[str]] = []
        repo = MagicMock()
        repo.git.commit.return_value = (0, "", "")

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch(
                "teleclaude.cli.telec.handlers.code._get_untracked_files",
                return_value=["teleclaude/brand_new.py"],
            ),
            patch("teleclaude.cli.telec.handlers.code._get_staged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._get_unmerged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged_files.append(files),
            ),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="feature"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
        ):
            _commit_under_lock(
                message="feat(scope): centralize scope",
                includes=[],
                project_root=tmp_path,
                system_role=None,
            )

        # Nothing staged (untracked dropped, modified doesn't need staging).
        assert staged_files == []
        # Pathspec contains ONLY the modified file; brand_new dropped.
        _assert_pathspec_commit(repo, ["teleclaude/modified.py"])
        # Behavioral assertion: the dropped file's PATH is surfaced so the
        # agent sees what got skipped. We do not lock the surrounding prose.
        assert "teleclaude/brand_new.py" in capsys.readouterr().err

    @pytest.mark.unit
    def test_pre_staged_untracked_in_scope_is_committed(self, tmp_path: Path) -> None:
        """If the agent ran `telec code add` first, the file is in the index;
        commit picks it up via pathspec without re-staging."""
        resolution = WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.WORKTREE,
            has_session_identity=False,
            dirty_paths=(
                DirtyPath("teleclaude/modified.py", DirtyOp.MODIFIED),
                DirtyPath("teleclaude/added.py", DirtyOp.MODIFIED),
            ),
            scoped_dirty_paths=("teleclaude/modified.py", "teleclaude/added.py"),
            scoped_existing_paths=("teleclaude/modified.py", "teleclaude/added.py"),
        )
        staged_files: list[list[str]] = []
        repo = MagicMock()
        repo.git.commit.return_value = (0, "", "")

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch(
                "teleclaude.cli.telec.handlers.code._get_untracked_files",
                return_value=["teleclaude/added.py"],
            ),
            patch(
                "teleclaude.cli.telec.handlers.code._get_staged_files",
                return_value=["teleclaude/added.py"],  # agent already ran telec code add
            ),
            patch("teleclaude.cli.telec.handlers.code._get_unmerged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged_files.append(files),
            ),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="feature"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
        ):
            _commit_under_lock(
                message="feat: new file declared explicitly",
                includes=[],
                project_root=tmp_path,
                system_role=None,
            )

        # added.py is already staged; no re-stage.
        assert staged_files == []
        _assert_pathspec_commit(repo, ["teleclaude/modified.py", "teleclaude/added.py"])

    @pytest.mark.unit
    def test_commit_skips_staging_when_all_scope_is_tracked(self, tmp_path: Path) -> None:
        """When every scope file is already tracked (modified/deleted), `_stage_files`
        is never called — the pathspec commit picks them up from the working tree."""
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
        staged_files: list[list[str]] = []
        repo = MagicMock()
        repo.git.commit.return_value = (0, "", "")

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._get_staged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._get_unmerged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged_files.append(files),
            ),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="feature"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
        ):
            _commit_under_lock(
                message="fix(scope): handle shared deletion",
                includes=[],
                project_root=tmp_path,
                system_role=None,
            )

        assert staged_files == []
        _assert_pathspec_commit(repo, ["teleclaude/deleted.py", "teleclaude/touched.py"])

    @pytest.mark.unit
    def test_foreign_pre_staged_file_left_in_index(self, tmp_path: Path) -> None:
        """Pathspec is the boundary: foreign staged files stay in the index.

        A pre-staged file outside scope is not in the commit pathspec and
        therefore not committed — it stays for its owner.
        """
        resolution = WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.SHARED_BRANCH,
            has_session_identity=True,
            dirty_paths=(DirtyPath("teleclaude/touched.py", DirtyOp.MODIFIED),),
            scoped_dirty_paths=("teleclaude/touched.py",),
            scoped_existing_paths=("teleclaude/touched.py",),
        )
        staged_files: list[list[str]] = []
        repo = MagicMock()
        repo.git.commit.return_value = (0, "", "")

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._get_staged_files", return_value=["foreign.py"]),
            patch("teleclaude.cli.telec.handlers.code._get_unmerged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged_files.append(files),
            ),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="feature"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
        ):
            _commit_under_lock(
                message="fix: own change",
                includes=[],
                project_root=tmp_path,
                system_role=None,
            )

        # touched.py is modified-tracked → not staged by us. Foreign files in
        # the index are simply absent from the pathspec → not committed.
        assert staged_files == []
        _assert_pathspec_commit(repo, ["teleclaude/touched.py"])

    @pytest.mark.unit
    def test_unmerged_file_in_scope_is_staged_for_commit(self, tmp_path: Path) -> None:
        """Integrator conflict path: an unmerged-index file (post-resolution)
        gets staged internally so git can complete the commit."""
        resolution = WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.WORKTREE,
            has_session_identity=False,
            dirty_paths=(DirtyPath("teleclaude/resolved.py", DirtyOp.MODIFIED),),
            scoped_dirty_paths=("teleclaude/resolved.py",),
            scoped_existing_paths=("teleclaude/resolved.py",),
        )
        staged_files: list[list[str]] = []
        repo = MagicMock()
        repo.git.commit.return_value = (0, "", "")

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._get_staged_files", return_value=[]),
            patch(
                "teleclaude.cli.telec.handlers.code._get_unmerged_files",
                return_value=["teleclaude/resolved.py"],
            ),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged_files.append(files),
            ),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="feature"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
        ):
            _commit_under_lock(
                message="merge: integrator conflict",
                includes=[],
                project_root=tmp_path,
                system_role="integrator",
            )

        # Unmerged-in-pathspec was staged so git could commit the resolution.
        assert staged_files == [["teleclaude/resolved.py"]]
        _assert_pathspec_commit(repo, ["teleclaude/resolved.py"])


class TestIncludeFlag:
    """``--include`` declares files outside the resolved workspace scope.

    The pathspec is the boundary: scope plus includes are committed; everything
    else in the index stays put. No env-var override exists — ``--include``
    is the only way to extend scope, and the agent must name every path.
    """

    @staticmethod
    def _resolution(scoped: tuple[str, ...]) -> WorkspaceScopeResolution:
        return WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.SHARED_BRANCH,
            has_session_identity=True,
            dirty_paths=tuple(DirtyPath(p, DirtyOp.MODIFIED) for p in scoped),
            scoped_dirty_paths=scoped,
            scoped_existing_paths=scoped,
        )

    @pytest.mark.unit
    def test_include_adds_path_to_pathspec(self, tmp_path: Path) -> None:
        """--include of a brand-new (untracked) file gets it staged AND included
        in the pathspec; the resolved scope file rides the pathspec untouched."""
        resolution = self._resolution(("teleclaude/mine.py",))
        staged_files: list[list[str]] = []
        repo = MagicMock()
        repo.git.commit.return_value = (0, "", "")
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch(
                "teleclaude.cli.telec.handlers.code._get_untracked_files",
                return_value=["teleclaude/extra.py"],
            ),
            patch(
                "teleclaude.cli.telec.handlers.code._dirty_paths",
                return_value={"teleclaude/mine.py", "teleclaude/extra.py"},
            ),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged_files.append(files),
            ),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="main"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
        ):
            _commit_under_lock(
                message="fix: mine plus extra",
                includes=["teleclaude/extra.py"],
                project_root=tmp_path,
                system_role=None,
            )
        assert staged_files == [["teleclaude/extra.py"]]
        _assert_pathspec_commit(repo, ["teleclaude/mine.py", "teleclaude/extra.py"])

    @pytest.mark.unit
    def test_include_of_modified_tracked_path_does_not_stage(self, tmp_path: Path) -> None:
        """--include of a modified-tracked file extends the pathspec but does
        not invoke _stage_files — pathspec alone commits modified-tracked content."""
        resolution = self._resolution(("teleclaude/mine.py",))
        staged_files: list[list[str]] = []
        repo = MagicMock()
        repo.git.commit.return_value = (0, "", "")
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch(
                "teleclaude.cli.telec.handlers.code._dirty_paths",
                return_value={"teleclaude/mine.py", "teleclaude/extra.py"},
            ),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged_files.append(files),
            ),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="main"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
        ):
            _commit_under_lock(
                message="fix: mine plus modified extra",
                includes=["teleclaude/extra.py"],
                project_root=tmp_path,
                system_role=None,
            )
        assert staged_files == []  # nothing untracked → no staging
        _assert_pathspec_commit(repo, ["teleclaude/mine.py", "teleclaude/extra.py"])

    @pytest.mark.unit
    def test_include_of_clean_path_errors(self, tmp_path: Path) -> None:
        """A declared --include path with no changes is a hard error."""
        resolution = self._resolution(("teleclaude/mine.py",))
        repo = MagicMock()
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch(
                "teleclaude.cli.telec.handlers.code._dirty_paths",
                return_value={"teleclaude/mine.py"},  # clean.py is NOT dirty
            ),
            patch("teleclaude.cli.telec.handlers.code._stage_files"),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="main"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
            pytest.raises(SystemExit) as exc,
        ):
            _commit_under_lock(
                message="fix: mine",
                includes=["teleclaude/clean.py"],
                project_root=tmp_path,
                system_role=None,
            )
        assert exc.value.code == 2
        repo.git.commit.assert_not_called()

    @pytest.mark.unit
    def test_include_dedupes_against_scope(self, tmp_path: Path) -> None:
        """An --include path that already appears in scope is not duplicated."""
        resolution = self._resolution(("teleclaude/mine.py",))
        repo = MagicMock()
        repo.git.commit.return_value = (0, "", "")
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch(
                "teleclaude.cli.telec.handlers.code._dirty_paths",
                return_value={"teleclaude/mine.py"},
            ),
            patch("teleclaude.cli.telec.handlers.code._stage_files"),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="main"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
        ):
            _commit_under_lock(
                message="fix: mine",
                includes=["teleclaude/mine.py"],
                project_root=tmp_path,
                system_role=None,
            )
        _assert_pathspec_commit(repo, ["teleclaude/mine.py"])

    @pytest.mark.unit
    def test_no_scope_no_includes_errors(self, tmp_path: Path) -> None:
        """Empty scope plus empty includes → nothing to commit, hard error."""
        resolution = self._resolution(())
        repo = MagicMock()
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._stage_files"),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="main"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
            pytest.raises(SystemExit) as exc,
        ):
            _commit_under_lock(
                message="fix: nothing",
                includes=[],
                project_root=tmp_path,
                system_role=None,
            )
        assert exc.value.code == 1
        repo.git.commit.assert_not_called()


class TestRustCommitContract:
    """Rust commits go through pre-commit hooks like every other language."""

    @pytest.mark.unit
    def test_rust_commit_path_does_not_call_quality_handlers_directly(self, tmp_path: Path) -> None:
        """telec code commit invokes git commit; cargo remains a pre-commit concern."""
        resolution = WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.WORKTREE,
            has_session_identity=False,
            dirty_paths=(DirtyPath("crates/workflow/src/lib.rs", DirtyOp.MODIFIED),),
            scoped_dirty_paths=("crates/workflow/src/lib.rs",),
            scoped_existing_paths=("crates/workflow/src/lib.rs",),
        )
        staged_files: list[list[str]] = []
        repo = MagicMock()
        repo.git.commit.return_value = (0, "", "")

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged_files.append(files),
            ),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="feature"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
            patch("teleclaude.cli.telec.handlers.code.handle_lint") as lint_handler,
            patch("teleclaude.cli.telec.handlers.code.handle_test") as test_handler,
            patch("teleclaude.cli.telec.handlers.code.handle_format") as format_handler,
        ):
            _commit_under_lock(
                message="chore(rust): smoke test",
                includes=[],
                project_root=tmp_path,
                system_role=None,
            )

        # Modified-tracked .rs file: no staging, pathspec commits it directly.
        assert staged_files == []
        lint_handler.assert_not_called()
        test_handler.assert_not_called()
        format_handler.assert_not_called()
        _assert_pathspec_commit(repo, ["crates/workflow/src/lib.rs"])


class TestPartialStagingGuard:
    """`git commit -- <path>` records the working-tree version of <path>,
    not just the staged hunks. A partially-staged file in the pathspec
    would silently sweep unstaged hunks into the commit. The guard blocks
    that and tells the agent to fully (re)stage."""

    @pytest.mark.unit
    def test_partial_staging_in_pathspec_blocks_commit(self, tmp_path: Path) -> None:
        resolution = WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.WORKTREE,
            has_session_identity=False,
            dirty_paths=(DirtyPath("teleclaude/mine.py", DirtyOp.MODIFIED),),
            scoped_dirty_paths=("teleclaude/mine.py",),
            scoped_existing_paths=("teleclaude/mine.py",),
        )
        repo = MagicMock()
        # diff(--cached --name-only) and diff(--name-only) both list mine.py
        # → it's both staged AND has unstaged delta → partial staging.
        repo.git.diff.return_value = "teleclaude/mine.py"

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._get_staged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._get_unmerged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._stage_files"),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="feature"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
            pytest.raises(SystemExit) as exc,
        ):
            _commit_under_lock(
                message="fix: mine",
                includes=[],
                project_root=tmp_path,
                system_role=None,
            )
        assert exc.value.code == 1
        repo.git.commit.assert_not_called()

    @pytest.mark.unit
    def test_foreign_partial_staging_outside_pathspec_does_not_block(self, tmp_path: Path) -> None:
        """A foreign file that is partial-staged outside our pathspec is not
        our problem — the pathspec excludes it from the commit anyway."""
        resolution = WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.SHARED_BRANCH,
            has_session_identity=True,
            dirty_paths=(DirtyPath("teleclaude/mine.py", DirtyOp.MODIFIED),),
            scoped_dirty_paths=("teleclaude/mine.py",),
            scoped_existing_paths=("teleclaude/mine.py",),
        )
        repo = MagicMock()
        # foreign.py is both staged and unstaged (partial), mine.py is clean
        # in the index (modified-tracked, rides pathspec).
        repo.git.diff.return_value = "foreign.py"
        repo.git.commit.return_value = (0, "", "")

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._get_staged_files", return_value=["foreign.py"]),
            patch("teleclaude.cli.telec.handlers.code._get_unmerged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._stage_files"),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="feature"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
        ):
            _commit_under_lock(
                message="fix: mine",
                includes=[],
                project_root=tmp_path,
                system_role=None,
            )
        # Commit proceeds because foreign.py is not in our pathspec.
        repo.git.commit.assert_called_once()


class TestHandleCodeAdd:
    """`telec code add` is the sealed equivalent of `git add` for NEW files.

    Stages untracked or unmerged paths only; refuses clean paths; no-ops
    with friendly guidance on already-tracked-modified paths (which don't
    need staging).
    """

    @pytest.mark.unit
    def test_no_args_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            handle_code_add([])
        assert exc.value.code == 2
        # Behavioral: some diagnostic is emitted on stderr; we don't lock prose.
        assert capsys.readouterr().err.strip() != ""

    @pytest.mark.unit
    def test_unknown_flag_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc:
            handle_code_add(["--bogus", "x.py"])
        assert exc.value.code == 2

    @pytest.mark.unit
    def test_stages_untracked_file(self, tmp_path: Path) -> None:
        new_file = tmp_path / "new.py"
        new_file.write_text("print('hi')\n")
        staged: list[list[str]] = []
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=["new.py"]),
            patch("teleclaude.cli.telec.handlers.code._get_unmerged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
            patch(
                "teleclaude.cli.telec.handlers.code.Repo",
                return_value=MagicMock(git=MagicMock(diff=MagicMock(return_value=""))),
            ),
            patch("teleclaude.cli.telec.handlers.code._dirty_paths", return_value={"new.py"}),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged.append(files),
            ),
        ):
            handle_code_add(["new.py"])
        # Structural: the contract is carried by the _stage_files call —
        # the file was handed to the staging primitive. No prose assertion.
        assert staged == [["new.py"]]

    @pytest.mark.unit
    def test_stages_partial_staged_tracked_file(self, tmp_path: Path) -> None:
        """The partial-staging guard recovery path. A tracked file with both
        staged hunks and a later unstaged delta is the failure mode the guard
        catches — `telec code add` is the prescribed recovery, so it must
        fully (re)stage the file rather than no-op as "already tracked"."""
        f = tmp_path / "partial.py"
        f.write_text("changed\n")
        staged: list[list[str]] = []
        repo = MagicMock()
        # The file appears in BOTH the staged list and the unstaged list →
        # partial staging.
        repo.git.diff.side_effect = ["partial.py", "partial.py"]
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._get_unmerged_files", return_value=[]),
            patch(
                "teleclaude.cli.telec.handlers.code.Repo",
                return_value=MagicMock(git=MagicMock(diff=MagicMock(return_value=""))),
            ),
            patch("teleclaude.cli.telec.handlers.code._dirty_paths", return_value={"partial.py"}),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged.append(files),
            ),
        ):
            handle_code_add(["partial.py"])
        # Behavioral: the partial-staged file was (re)staged, not no-oped.
        assert staged == [["partial.py"]]

    @pytest.mark.unit
    def test_stages_partial_staged_deleted_file(self, tmp_path: Path) -> None:
        """Partial-staged + working-tree DELETION: staged edit followed by
        a deletion in the working tree. The file does not exist on disk
        anymore, but the path is in BOTH staged and unstaged diffs. The
        recovery must still accept it (check `partial_staged` BEFORE the
        existence check)."""
        # Note: do NOT write the file — simulate the post-deletion state.
        staged: list[list[str]] = []
        repo = MagicMock()
        repo.git.diff.side_effect = ["deleted.py", "deleted.py"]
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._get_unmerged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._dirty_paths", return_value={"deleted.py"}),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged.append(files),
            ),
        ):
            handle_code_add(["deleted.py"])
        # Structural: the deleted path was (re)staged, not rejected as missing.
        assert staged == [["deleted.py"]]

    @pytest.mark.unit
    def test_stages_unmerged_file(self, tmp_path: Path) -> None:
        """Conflict-resolved files (unmerged-index state) are stageable via this command."""
        resolved = tmp_path / "resolved.py"
        resolved.write_text("merged content\n")
        staged: list[list[str]] = []
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._get_unmerged_files", return_value=["resolved.py"]),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
            patch(
                "teleclaude.cli.telec.handlers.code.Repo",
                return_value=MagicMock(git=MagicMock(diff=MagicMock(return_value=""))),
            ),
            patch("teleclaude.cli.telec.handlers.code._dirty_paths", return_value={"resolved.py"}),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged.append(files),
            ),
        ):
            handle_code_add(["resolved.py"])
        assert staged == [["resolved.py"]]

    @pytest.mark.unit
    def test_already_tracked_modified_is_noop_with_note(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A modified-tracked file doesn't need `add`; emit a friendly note,
        no error, no staging — the pathspec commit will pick it up directly."""
        f = tmp_path / "tracked.py"
        f.write_text("changed\n")
        staged: list[list[str]] = []
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._get_unmerged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
            patch(
                "teleclaude.cli.telec.handlers.code.Repo",
                return_value=MagicMock(git=MagicMock(diff=MagicMock(return_value=""))),
            ),
            patch("teleclaude.cli.telec.handlers.code._dirty_paths", return_value={"tracked.py"}),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged.append(files),
            ),
        ):
            handle_code_add(["tracked.py"])
        assert staged == []
        # Behavioral: the modified-tracked file is named in the note; we do
        # not lock the surrounding prose ("already tracked").
        assert "tracked.py" in capsys.readouterr().err

    @pytest.mark.unit
    def test_clean_path_errors(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        f = tmp_path / "clean.py"
        f.write_text("nothing changed\n")
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._get_unmerged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
            patch(
                "teleclaude.cli.telec.handlers.code.Repo",
                return_value=MagicMock(git=MagicMock(diff=MagicMock(return_value=""))),
            ),
            patch("teleclaude.cli.telec.handlers.code._dirty_paths", return_value=set()),
            patch("teleclaude.cli.telec.handlers.code._stage_files"),
            pytest.raises(SystemExit) as exc,
        ):
            handle_code_add(["clean.py"])
        assert exc.value.code == 2
        # Behavioral: the offending path is named so the agent can act on it.
        assert "clean.py" in capsys.readouterr().err

    @pytest.mark.unit
    def test_missing_path_errors(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=tmp_path),
            patch("teleclaude.cli.telec.handlers.code._get_untracked_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._get_unmerged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
            patch(
                "teleclaude.cli.telec.handlers.code.Repo",
                return_value=MagicMock(git=MagicMock(diff=MagicMock(return_value=""))),
            ),
            patch("teleclaude.cli.telec.handlers.code._dirty_paths", return_value=set()),
            patch("teleclaude.cli.telec.handlers.code._stage_files"),
            pytest.raises(SystemExit) as exc,
        ):
            handle_code_add(["does-not-exist.py"])
        assert exc.value.code == 2
        # Behavioral: the offending path is named in the error.
        assert "does-not-exist.py" in capsys.readouterr().err


class TestExcludedFiles:
    """Structural guards: certain files must not be modified by the current todo."""

    @pytest.mark.unit
    def test_excluded_pre_commit_config_has_no_branch_diff(self) -> None:
        """The todo must not modify .pre-commit-config.yaml."""
        assert _branch_diff(".pre-commit-config.yaml") == []

    @pytest.mark.unit
    def test_excluded_teleclaude_yml_has_no_branch_diff(self) -> None:
        """The todo must not modify teleclaude.yml."""
        assert _branch_diff("teleclaude.yml") == []


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


def _assert_pathspec_commit(repo, expected_files: list[str]) -> None:
    """Assert the commit ran as a pathspec commit via a message file (-F)."""
    repo.git.commit.assert_called_once()
    args, kwargs = repo.git.commit.call_args
    assert args[0] == "-F"
    assert isinstance(args[1], str) and args[1]
    assert args[2] == "--"
    assert list(args[3:]) == expected_files
    assert kwargs == {"with_extended_output": True}


def _branch_diff(path: str) -> list[str]:
    merge_base = subprocess.run(
        ["git", "merge-base", "HEAD", "main"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if merge_base.returncode != 0:
        pytest.skip("main branch is unavailable for structural branch-diff check")
    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{merge_base.stdout.strip()}..HEAD", "--", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if diff.returncode != 0:
        pytest.skip("git diff is unavailable for structural branch-diff check")
    return [line for line in diff.stdout.splitlines() if line]


class TestWithTrailer:
    @pytest.mark.unit
    def test_appends_trailer_when_absent(self) -> None:
        out = _with_trailer("fix(x): y")
        assert out.startswith("fix(x): y\n\n")
        assert "Co-Authored-By: TeleClaude <noreply@instrukt.ai>" in out
        assert out.endswith("\n")

    @pytest.mark.unit
    def test_idempotent_when_trailer_present(self) -> None:
        already = "fix(x): y\n\n\U0001f916 Generated with [TeleClaude](u)\n\nCo-Authored-By: X <a@b>"
        assert _with_trailer(already).count("Generated with [TeleClaude]") == 1


class TestHandleCodeCommitContract:
    @pytest.mark.unit
    def test_bare_call_on_main_prints_abc_classification(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Bare `telec code commit` on main surfaces Path A/B/C (exit 1)."""
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=Path("/r")),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=Path("/r")),
            patch("teleclaude.cli.telec.handlers.code.get_system_role", return_value=None),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="main"),
            pytest.raises(SystemExit) as exc,
        ):
            handle_code_commit([])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Commits on main require classification" in err

    @pytest.mark.unit
    def test_rejects_dash_m_flag(self) -> None:
        with pytest.raises(SystemExit) as exc:
            handle_code_commit(["-m", "fix: x"])
        assert exc.value.code == 2

    @pytest.mark.unit
    def test_rejects_extra_positional(self) -> None:
        with pytest.raises(SystemExit) as exc:
            handle_code_commit(["fix: x", "extra"])
        assert exc.value.code == 2

    @pytest.mark.unit
    def test_message_without_approved_also_surfaces_abc(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Missing --approved is the ABC trigger — message presence is irrelevant."""
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=Path("/r")),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=Path("/r")),
            patch("teleclaude.cli.telec.handlers.code.get_system_role", return_value=None),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="main"),
            pytest.raises(SystemExit) as exc,
        ):
            handle_code_commit(["fix(x): y"])
        assert exc.value.code == 1
        # Behavioral: the ABC card emits the three classification labels as
        # structural markers (A), B), C)). Asserts on those — not the
        # surrounding prose — so wording can evolve without breaking tests.
        err = capsys.readouterr().err
        assert "A)" in err and "B)" in err and "C)" in err

    @pytest.mark.unit
    def test_approved_without_message_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc:
            handle_code_commit(["--approved"])
        assert exc.value.code == 2

    @pytest.mark.unit
    def test_approved_with_message_forwards_to_commit(self) -> None:
        with (
            patch("teleclaude.cli.telec.handlers.code.main_branch_lock"),
            patch("teleclaude.cli.telec.handlers.code._commit_under_lock") as under_lock,
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=Path("/r")),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=Path("/r")),
            patch("teleclaude.cli.telec.handlers.code.get_system_role", return_value=None),
        ):
            handle_code_commit(["fix(x): y", "--approved"])
        assert under_lock.call_count == 1
        assert under_lock.call_args.kwargs["message"] == "fix(x): y"
        assert under_lock.call_args.kwargs["includes"] == []

    @pytest.mark.unit
    def test_approved_with_include_forwards_paths(self) -> None:
        """--include collects subsequent non-flag tokens into the includes bucket."""
        with (
            patch("teleclaude.cli.telec.handlers.code.main_branch_lock"),
            patch("teleclaude.cli.telec.handlers.code._commit_under_lock") as under_lock,
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=Path("/r")),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=Path("/r")),
            patch("teleclaude.cli.telec.handlers.code.get_system_role", return_value=None),
        ):
            handle_code_commit(["--approved", "fix(x): y", "--include", "a.py", "b.py"])
        assert under_lock.call_args.kwargs["message"] == "fix(x): y"
        assert under_lock.call_args.kwargs["includes"] == ["a.py", "b.py"]

    @pytest.mark.unit
    def test_approved_resets_include_mode(self) -> None:
        """--approved after --include resets parsing back to positional mode."""
        with (
            patch("teleclaude.cli.telec.handlers.code.main_branch_lock"),
            patch("teleclaude.cli.telec.handlers.code._commit_under_lock") as under_lock,
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=Path("/r")),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=Path("/r")),
            patch("teleclaude.cli.telec.handlers.code.get_system_role", return_value=None),
        ):
            handle_code_commit(["--include", "a.py", "b.py", "--approved", "fix(x): y"])
        assert under_lock.call_args.kwargs["message"] == "fix(x): y"
        assert under_lock.call_args.kwargs["includes"] == ["a.py", "b.py"]

    @pytest.mark.unit
    def test_include_consumes_message_when_misplaced(self, capsys: pytest.CaptureFixture[str]) -> None:
        """If the message comes after --include, it gets swallowed into includes
        and we error because no message remains."""
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=Path("/r")),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=Path("/r")),
            patch("teleclaude.cli.telec.handlers.code.get_system_role", return_value=None),
            patch("teleclaude.cli.telec.handlers.code.main_branch_lock"),
            patch("teleclaude.cli.telec.handlers.code._commit_under_lock"),
            pytest.raises(SystemExit) as exc,
        ):
            # message "fix: x" goes into includes; --approved set; no positional.
            handle_code_commit(["--approved", "--include", "a.py", "fix: x"])
        assert exc.value.code == 2
        # Behavioral: a diagnostic is emitted on stderr; exit code carries
        # the contract. We don't lock the surrounding prose.
        assert capsys.readouterr().err.strip() != ""

    @pytest.mark.unit
    def test_unknown_flag_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc:
            handle_code_commit(["--bogus", "fix: x"])
        assert exc.value.code == 2

    @pytest.mark.unit
    def test_include_with_no_operand_at_end_rejected(self) -> None:
        """--include followed by nothing must fail fast, not be silently ignored."""
        with pytest.raises(SystemExit) as exc:
            handle_code_commit(["--approved", "fix: x", "--include"])
        assert exc.value.code == 2

    @pytest.mark.unit
    def test_include_immediately_followed_by_approved_rejected(self) -> None:
        """--include with no path before --approved closes the group empty."""
        with pytest.raises(SystemExit) as exc:
            handle_code_commit(["--include", "--approved", "fix: x"])
        assert exc.value.code == 2

    @pytest.mark.unit
    def test_double_include_with_empty_first_group_rejected(self) -> None:
        """Two --include flags with no path between is a fail-fast error."""
        with pytest.raises(SystemExit) as exc:
            handle_code_commit(["--approved", "fix: x", "--include", "--include", "a.py"])
        assert exc.value.code == 2
