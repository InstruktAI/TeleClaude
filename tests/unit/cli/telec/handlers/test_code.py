"""Tests for telec code commit classification and staging logic."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.cli.telec.handlers.code import (
    _commit_under_lock,
    _current_branch,
    _get_staged_files,
    _stage_files,
    _with_trailer,
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
        repo.git.commit.return_value = (0, "", "")

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
                includes=[],
                project_root=tmp_path,
                system_role=None,
            )

        assert staged_files == [["teleclaude/changed.py", "teleclaude/deleted.py"]]
        _assert_pathspec_commit(repo, ["teleclaude/changed.py", "teleclaude/deleted.py"])

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
        repo.git.commit.return_value = (0, "", "")

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
                includes=[],
                project_root=tmp_path,
                system_role=None,
            )

        # deleted.py was already staged (pre_staged) → not re-staged; touched.py was not → staged.
        assert staged_files == [["teleclaude/touched.py"]]
        # Pathspec includes both — the index has both, and both are in scope.
        _assert_pathspec_commit(repo, ["teleclaude/deleted.py", "teleclaude/touched.py"])

    @pytest.mark.unit
    def test_foreign_pre_staged_file_left_in_index(self, tmp_path: Path) -> None:
        """Pathspec is the boundary: foreign staged files stay in the index.

        On any shared-branch invocation, the pathspec equals (workspace scope
        plus includes). A pre-staged file outside that set is not in the commit
        and stays staged for its owner — no special-case "trust the index"
        behavior, no foreign-files diagnostic.
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
        # pre_staged: foreign is already staged; staged_after: foreign + ours.
        staged_snapshots = [
            ["teleclaude/foreign_deleted.py"],
            ["teleclaude/foreign_deleted.py", "teleclaude/touched.py"],
        ]
        staged_files: list[list[str]] = []
        repo = MagicMock()
        repo.git.commit.return_value = (0, "", "")

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
                includes=[],
                project_root=tmp_path,
                system_role=None,
            )

        assert staged_files == [["teleclaude/touched.py"]]
        # Pathspec contains ONLY our scope; foreign_deleted.py is left in the
        # index for its owner to commit or unstage.
        _assert_pathspec_commit(repo, ["teleclaude/touched.py"])


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
        """--include foo.py stages foo.py and adds it to the commit pathspec."""
        resolution = self._resolution(("teleclaude/mine.py",))
        # pre_staged: only mine (we'll stage it); staged_after: mine + extra.
        staged_snapshots = [
            ["teleclaude/mine.py"],
            ["teleclaude/extra.py", "teleclaude/mine.py"],
        ]
        staged_files: list[list[str]] = []
        repo = MagicMock()
        repo.git.commit.return_value = (0, "", "")
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_staged_files", side_effect=staged_snapshots),
            patch(
                "teleclaude.cli.telec.handlers.code._stage_files",
                side_effect=lambda files, _root: staged_files.append(files),
            ),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="main"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
        ):
            _commit_under_lock(
                message="fix: mine plus extra",
                includes=["teleclaude/extra.py"],
                project_root=tmp_path,
                system_role=None,
            )
        # extra.py wasn't pre-staged → got staged. Pathspec is scope plus includes.
        assert staged_files == [["teleclaude/extra.py"]]
        _assert_pathspec_commit(repo, ["teleclaude/mine.py", "teleclaude/extra.py"])

    @pytest.mark.unit
    def test_include_of_clean_path_errors(self, tmp_path: Path) -> None:
        """A declared --include path with no changes is a hard error."""
        resolution = self._resolution(("teleclaude/mine.py",))
        # pre_staged then staged_after both lack clean.py (git add is no-op).
        staged_snapshots = [
            ["teleclaude/mine.py"],
            ["teleclaude/mine.py"],
        ]
        repo = MagicMock()
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_staged_files", side_effect=staged_snapshots),
            patch("teleclaude.cli.telec.handlers.code._stage_files"),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
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
        staged_snapshots = [
            ["teleclaude/mine.py"],
            ["teleclaude/mine.py"],
        ]
        repo = MagicMock()
        repo.git.commit.return_value = (0, "", "")
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_staged_files", side_effect=staged_snapshots),
            patch("teleclaude.cli.telec.handlers.code._stage_files"),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
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
            patch("teleclaude.cli.telec.handlers.code._get_staged_files", return_value=[]),
            patch("teleclaude.cli.telec.handlers.code._stage_files"),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
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
        staged_snapshots = [
            [],
            ["crates/workflow/src/lib.rs"],
        ]
        staged_files: list[list[str]] = []
        repo = MagicMock()
        repo.git.commit.return_value = (0, "", "")

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

        assert staged_files == [["crates/workflow/src/lib.rs"]]
        lint_handler.assert_not_called()
        test_handler.assert_not_called()
        format_handler.assert_not_called()
        _assert_pathspec_commit(repo, ["crates/workflow/src/lib.rs"])


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
        assert "Commits on main require classification" in capsys.readouterr().err

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
        assert "--approved requires a quoted commit message" in capsys.readouterr().err

    @pytest.mark.unit
    def test_unknown_flag_rejected(self) -> None:
        with pytest.raises(SystemExit) as exc:
            handle_code_commit(["--bogus", "fix: x"])
        assert exc.value.code == 2
