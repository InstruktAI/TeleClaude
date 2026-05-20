"""Tests for telec code commit classification and staging logic."""

from __future__ import annotations

import subprocess
from contextlib import ExitStack
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
                project_root=tmp_path,
                system_role=None,
            )

        # deleted.py was already staged (pre_staged) → not re-staged; touched.py was not → staged.
        assert staged_files == [["teleclaude/touched.py"]]
        # Pathspec includes both — the index has both, and both are in scope.
        _assert_pathspec_commit(repo, ["teleclaude/deleted.py", "teleclaude/touched.py"])

    @pytest.mark.unit
    def test_non_main_branch_trusts_index_with_foreign_pre_staged_file(self, tmp_path: Path) -> None:
        """Non-main branches are user-owned: the scope gate does not apply.

        A feature branch in the project root is single-owner; whatever is in
        the index is trusted and committed, even pre-staged files outside the
        session scope. The scope gate is a shared-main concern only.
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
                project_root=tmp_path,
                system_role=None,
            )

        assert staged_files == [["teleclaude/touched.py"]]
        _assert_pathspec_commit(repo, ["teleclaude/foreign_deleted.py", "teleclaude/touched.py"])


class TestSessionScopeGate:
    """Stage-2 session-scope assertion on shared main.

    Independent of the Path A/B/C strategy gate. It runs after classification
    is satisfied and hard-fails when the index contains staged files outside
    this session's scope, unless the explicit ``TELECLAUDE_COMMIT_APPROVED``
    override is set. ``--approved`` answers "right strategy"; it never grants
    a license to commit another agent's staged files.
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

    def _run(
        self,
        tmp_path: Path,
        *,
        scoped: tuple[str, ...],
        staged: list[str],
        system_role: str | None,
        message: str,
    ) -> MagicMock:
        resolution = self._resolution(scoped)
        # _get_staged_files: pre_staged lookup (only if stage_paths non-empty), then staged_for_commit.
        snapshots = [staged, staged] if scoped else [staged]
        repo = MagicMock()
        repo.git.commit.return_value = (0, "", "")
        ctx = [
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_scope_resolution", return_value=resolution),
            patch("teleclaude.cli.telec.handlers.code._get_staged_files", side_effect=snapshots),
            patch("teleclaude.cli.telec.handlers.code._stage_files"),
            patch("teleclaude.cli.telec.handlers.code._check_partial_staging"),
            patch("teleclaude.cli.telec.handlers.code._current_branch", return_value="main"),
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=repo),
        ]
        with ExitStack() as stack:
            for cm in ctx:
                stack.enter_context(cm)
            _commit_under_lock(
                message=message,
                project_root=tmp_path,
                system_role=system_role,
            )
        return repo

    @pytest.mark.unit
    def test_foreign_staged_file_blocks_even_when_approved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--approved satisfies the ABC gate but never the scope gate."""
        monkeypatch.delenv("TELECLAUDE_COMMIT_APPROVED", raising=False)
        with pytest.raises(SystemExit) as exc:
            self._run(
                tmp_path,
                scoped=("teleclaude/mine.py",),
                staged=["teleclaude/foreign.py", "teleclaude/mine.py"],
                system_role=None,
                message="fix: mine",
            )
        assert exc.value.code == 2

    @pytest.mark.unit
    def test_env_override_allows_foreign_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """TELECLAUDE_COMMIT_APPROVED=1 is the deliberate alien-files escape."""
        monkeypatch.setenv("TELECLAUDE_COMMIT_APPROVED", "1")
        repo = self._run(
            tmp_path,
            scoped=("teleclaude/mine.py",),
            staged=["teleclaude/foreign.py", "teleclaude/mine.py"],
            system_role=None,
            message="chore: deliberate sweep",
        )
        _assert_pathspec_commit(repo, ["teleclaude/foreign.py", "teleclaude/mine.py"])

    @pytest.mark.unit
    def test_scoped_only_commit_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Index ⊆ session scope: the gate is a no-op."""
        monkeypatch.delenv("TELECLAUDE_COMMIT_APPROVED", raising=False)
        repo = self._run(
            tmp_path,
            scoped=("teleclaude/mine.py",),
            staged=["teleclaude/mine.py"],
            system_role=None,
            message="fix: only mine",
        )
        repo.git.commit.assert_called_once()

    @pytest.mark.unit
    def test_scope_unavailable_does_not_block(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No transcript signal → tolerant pre-staged fallback, no hard fail."""
        monkeypatch.delenv("TELECLAUDE_COMMIT_APPROVED", raising=False)
        repo = self._run(
            tmp_path,
            scoped=(),
            staged=["teleclaude/anything.py"],
            system_role=None,
            message="fix: pre-staged fallback",
        )
        repo.git.commit.assert_called_once()

    @pytest.mark.unit
    def test_integrator_bypasses_scope_gate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The integrator legitimately commits aggregated work."""
        monkeypatch.delenv("TELECLAUDE_COMMIT_APPROVED", raising=False)
        repo = self._run(
            tmp_path,
            scoped=("teleclaude/mine.py",),
            staged=["teleclaude/foreign.py", "teleclaude/mine.py"],
            system_role="integrator",
            message="merge: integrate",
        )
        repo.git.commit.assert_called_once()

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
                project_root=tmp_path,
                system_role=None,
            )

        assert staged_files == [["crates/workflow/src/lib.rs"]]
        lint_handler.assert_not_called()
        test_handler.assert_not_called()
        format_handler.assert_not_called()
        _assert_pathspec_commit(repo, ["crates/workflow/src/lib.rs"])

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
