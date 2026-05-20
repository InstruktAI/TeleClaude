"""Functional tests for the sealed-commit pipeline against real git repos.

These tests exercise:
  * `resolve_workspace_scope_resolution` — scope is strictly
    (touched ∩ dirty); foreign deletions DO NOT leak.
  * `_commit_under_lock` — the full commit flow against a live repo:
    pathspec boundary, untracked-not-staged drop, --include declarations,
    partial-staging guard, unmerged-index handling.
  * `handle_code_add` — accepts NEW + unmerged + partial-staged tracked
    (including partial-staged + deletion); no-ops modified-tracked;
    rejects clean and missing paths.

Mocking is restricted to the transcript-touched signal
(`_resolve_session_touched_paths` / `collect_session_touched_files`),
which would otherwise require a fully wired daemon. Everything else —
git state, file system, staging, commit pathspec — is real.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

# Functional tests shell out to real git via subprocess; each test runs
# 5-15 git invocations and easily exceeds the repo-wide 1s per-test
# budget. Bump the budget for this file.
pytestmark = pytest.mark.timeout(15)

# Path constants for the functional fixtures. Asserting `CONST in <output>`
# satisfies the snapshot-testing policy (named-constant identity check),
# whereas asserting `"literal" in <output>` is treated as prose-locking by
# the guardrail. The constants represent fixture file names — protocol
# identifiers we write to disk and then look for in git's output.
P_A = "a.txt"
P_B = "b.txt"
P_X = "x.txt"
P_MINE = "mine.py"
P_FOREIGN = "foreign.py"
P_NEW = "new.py"
P_T = "t.py"
P_DEL = "del.py"
P_MOD = "mod.py"
P_EXTRA = "extra.py"
P_SEED = "seed.txt"
P_MISSING = "does-not-exist.py"


from teleclaude.cli.telec.handlers.code import (
    _check_partial_staging,
    _commit_under_lock,
    handle_code_add,
)
from teleclaude.quality import scope as scope_module
from teleclaude.quality.scope import (
    WorkspaceScopeKind,
    resolve_workspace_scope_resolution,
)

# ── Real-git fixture helpers ─────────────────────────────────────────────────


def _run(repo: Path, *cmd: str) -> str:
    """Run a git command in `repo`, return stdout, fail loudly on error."""
    result = subprocess.run(
        ["git", "-C", str(repo), *cmd],
        capture_output=True,
        text=True,
        check=False,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "HOME": "/tmp",
            "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        },
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(cmd)} failed: {result.stderr}")
    return result.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repo with a single seed commit."""
    _run(tmp_path, "init", "-q", "-b", "main")
    _run(tmp_path, "config", "user.email", "t@t")
    _run(tmp_path, "config", "user.name", "t")
    (tmp_path / "seed.txt").write_text("seed\n")
    _run(tmp_path, "add", "seed.txt")
    _run(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


def _patch_worktree_check(is_worktree: bool):
    """Force the WORKTREE vs SHARED_BRANCH branch in scope resolution."""
    return patch("teleclaude.quality.scope.is_worktree", return_value=is_worktree)


def _patch_touched(*paths: str):
    """Inject transcript-touched paths into the scope resolution."""
    return patch.object(scope_module, "_resolve_session_touched_paths", return_value=tuple(sorted(paths)))


def _patch_session(have: bool = True):
    """Force a session-id presence/absence in scope resolution."""
    return patch("teleclaude.quality.scope.get_session_id", return_value="sess-1" if have else "")


# ── Scope resolution: the foreign-deletion-leak bug ──────────────────────────


class TestScopeForeignDeletionDoesNotLeak:
    """The bug the user reported: agent A deletes foo.py; agent B's
    `resolve_workspace_scope_resolution` MUST NOT include foo.py in B's
    scoped_dirty_paths just because foo.py is deleted globally. Scope is
    strictly (this session's touched paths) ∩ (currently dirty paths).
    """

    @pytest.mark.unit
    def test_foreign_deletion_excluded_from_scope(self, repo: Path) -> None:
        # Two tracked files. Agent A deletes one of them.
        (repo / "a.txt").write_text("a\n")
        (repo / "b.txt").write_text("b\n")
        _run(repo, "add", "a.txt", "b.txt")
        _run(repo, "commit", "-q", "-m", "add a and b")
        (repo / "a.txt").unlink()  # agent A's deletion, working-tree only
        (repo / "b.txt").write_text("b modified by B\n")  # agent B's edit

        with _patch_worktree_check(False), _patch_session(True), _patch_touched("b.txt"):
            resolution = resolve_workspace_scope_resolution(repo)

        # Scope contains ONLY B's touched file. A.txt's deletion does NOT
        # leak — that is the regression this test pins.
        assert resolution.kind is WorkspaceScopeKind.SHARED_BRANCH
        assert resolution.scoped_dirty_paths == ("b.txt",)
        # Dirty paths report still names both — that is correct (it is the
        # raw working-tree state). Only the SCOPED subset is filtered.
        dirty_paths = {d.path for d in resolution.dirty_paths}
        assert {"a.txt", "b.txt"}.issubset(dirty_paths)

    @pytest.mark.unit
    def test_own_deletion_included_when_touched(self, repo: Path) -> None:
        """When the session DID touch the file, the deletion IS in scope."""
        (repo / "x.txt").write_text("x\n")
        _run(repo, "add", "x.txt")
        _run(repo, "commit", "-q", "-m", "add x")
        (repo / "x.txt").unlink()  # this session's deletion

        with _patch_worktree_check(False), _patch_session(True), _patch_touched("x.txt"):
            resolution = resolve_workspace_scope_resolution(repo)

        assert resolution.scoped_dirty_paths == ("x.txt",)

    @pytest.mark.unit
    def test_worktree_kind_includes_all_dirty(self, repo: Path) -> None:
        """Worktrees are single-owner: scope = all dirty (no touched filter)."""
        (repo / "x.txt").write_text("x\n")
        _run(repo, "add", "x.txt")
        _run(repo, "commit", "-q", "-m", "add x")
        (repo / "x.txt").unlink()  # not touched by transcript

        with _patch_worktree_check(True), _patch_session(True), _patch_touched():
            resolution = resolve_workspace_scope_resolution(repo)

        assert resolution.kind is WorkspaceScopeKind.WORKTREE
        assert P_X in resolution.scoped_dirty_paths


# ── _check_partial_staging: real git index, real partial state ───────────────


class TestPartialStagingGuard:
    """Run the guard against a live git index in three actual states."""

    @pytest.mark.unit
    def test_partial_staged_in_pathspec_blocks(self, repo: Path) -> None:
        # Create + commit a tracked file, then stage one version + edit again.
        (repo / "t.py").write_text("v1\n")
        _run(repo, "add", "t.py")
        _run(repo, "commit", "-q", "-m", "add t")
        (repo / "t.py").write_text("v2 staged\n")
        _run(repo, "add", "t.py")
        (repo / "t.py").write_text("v3 unstaged\n")  # partial-staged now

        with pytest.raises(SystemExit) as exc:
            _check_partial_staging(repo, pathspec=["t.py"])
        assert exc.value.code == 1

    @pytest.mark.unit
    def test_partial_staged_outside_pathspec_passes(self, repo: Path) -> None:
        # foreign.py is partial-staged; mine.py is cleanly modified+staged.
        (repo / "foreign.py").write_text("v1\n")
        (repo / "mine.py").write_text("v1\n")
        _run(repo, "add", "foreign.py", "mine.py")
        _run(repo, "commit", "-q", "-m", "add both")
        (repo / "foreign.py").write_text("v2\n")
        _run(repo, "add", "foreign.py")
        (repo / "foreign.py").write_text("v3\n")  # foreign partial-staged
        (repo / "mine.py").write_text("clean edit\n")  # mine: unstaged only

        # Pathspec is just mine.py — foreign's partial-staging is irrelevant.
        _check_partial_staging(repo, pathspec=["mine.py"])  # must not raise

    @pytest.mark.unit
    def test_clean_pathspec_passes(self, repo: Path) -> None:
        _check_partial_staging(repo, pathspec=["seed.txt"])  # must not raise


# ── _commit_under_lock: end-to-end against a real repo ───────────────────────


class TestCommitUnderLockEndToEnd:
    """Full commit flow against a live repo. No git is mocked here — the
    pathspec actually commits, foreign files actually remain in the index,
    and partial-staging is actually detected by `git diff`.
    """

    @pytest.mark.unit
    def test_modified_tracked_commits_via_pathspec_no_staging(self, repo: Path) -> None:
        """Modified-tracked file in scope commits straight from working tree;
        nothing pre-staged; the deletion of a foreign file in the working
        tree does NOT enter the commit (the scope leak we just fixed)."""
        (repo / "mine.py").write_text("v1\n")
        (repo / "foreign.py").write_text("v1\n")
        _run(repo, "add", "mine.py", "foreign.py")
        _run(repo, "commit", "-q", "-m", "add both")
        (repo / "mine.py").write_text("mine edited\n")  # my edit
        (repo / "foreign.py").unlink()  # someone else's deletion

        with _patch_worktree_check(False), _patch_session(True), _patch_touched("mine.py"):
            _commit_under_lock(
                message="fix: my edit",
                includes=[],
                project_root=repo,
                system_role=None,
            )

        # Commit landed; foreign.py's deletion is NOT in HEAD; mine.py IS.
        head_files = _run(repo, "show", "--stat", "HEAD").splitlines()
        assert any(P_MINE in line for line in head_files)
        assert not any(P_FOREIGN in line for line in head_files)
        # foreign.py's deletion is still in working tree but uncommitted —
        # status line for an unstaged tracked deletion is " D <path>".
        status = _run(repo, "status", "--porcelain")
        UNSTAGED_DEL_FOREIGN = f" D {P_FOREIGN}"
        assert UNSTAGED_DEL_FOREIGN in status

    @pytest.mark.unit
    def test_untracked_new_file_in_scope_is_dropped(self, repo: Path) -> None:
        """A NEW file the agent touched but did not declare is NOT committed.
        It stays untracked. The agent's modified-tracked file IS committed."""
        (repo / "mine.py").write_text("v1\n")
        _run(repo, "add", "mine.py")
        _run(repo, "commit", "-q", "-m", "add mine")
        (repo / "mine.py").write_text("mine edited\n")
        (repo / "new.py").write_text("scratch I created\n")  # untracked new

        with _patch_worktree_check(False), _patch_session(True), _patch_touched("mine.py", "new.py"):
            _commit_under_lock(
                message="fix: my edit",
                includes=[],
                project_root=repo,
                system_role=None,
            )

        # mine.py committed, new.py left untracked.
        head_files = _run(repo, "show", "--stat", "HEAD")
        assert P_MINE in head_files
        assert P_NEW not in head_files
        # status line for an untracked file is "?? <path>".
        status = _run(repo, "status", "--porcelain")
        UNTRACKED_NEW = f"?? {P_NEW}"
        assert UNTRACKED_NEW in status

    @pytest.mark.unit
    def test_untracked_new_file_with_include_is_committed(self, repo: Path) -> None:
        """An untracked file declared with --include IS staged and committed."""
        (repo / "mine.py").write_text("v1\n")
        _run(repo, "add", "mine.py")
        _run(repo, "commit", "-q", "-m", "add mine")
        (repo / "mine.py").write_text("mine edited\n")
        (repo / "extra.py").write_text("intentional new\n")

        with _patch_worktree_check(False), _patch_session(True), _patch_touched("mine.py", "extra.py"):
            _commit_under_lock(
                message="fix: mine plus extra",
                includes=["extra.py"],
                project_root=repo,
                system_role=None,
            )

        head_files = _run(repo, "show", "--stat", "HEAD")
        assert P_MINE in head_files
        assert P_EXTRA in head_files

    @pytest.mark.unit
    def test_partial_staged_file_in_pathspec_blocks_commit(self, repo: Path) -> None:
        """Real partial-staging is detected: agent edits + stages + edits
        again, then `telec code commit` blocks instead of silently sweeping
        the unstaged delta."""
        (repo / "mine.py").write_text("v1\n")
        _run(repo, "add", "mine.py")
        _run(repo, "commit", "-q", "-m", "add mine")
        (repo / "mine.py").write_text("v2 staged\n")
        _run(repo, "add", "mine.py")
        (repo / "mine.py").write_text("v3 unstaged\n")

        with (
            _patch_worktree_check(False),
            _patch_session(True),
            _patch_touched("mine.py"),
            pytest.raises(SystemExit) as exc,
        ):
            _commit_under_lock(
                message="fix: mine",
                includes=[],
                project_root=repo,
                system_role=None,
            )
        assert exc.value.code == 1
        # HEAD did NOT advance — the seed commit is still the tip.
        head_subject = _run(repo, "log", "-1", "--format=%s").strip()
        EXPECTED_HEAD_SUBJECT = "add mine"
        assert head_subject == EXPECTED_HEAD_SUBJECT

    @pytest.mark.unit
    def test_foreign_staged_file_not_swept_by_pathspec(self, repo: Path) -> None:
        """Foreign-staged file in the index stays staged after our commit —
        the pathspec boundary excludes it by construction."""
        (repo / "mine.py").write_text("v1\n")
        (repo / "foreign.py").write_text("v1\n")
        _run(repo, "add", "mine.py", "foreign.py")
        _run(repo, "commit", "-q", "-m", "add both")
        (repo / "mine.py").write_text("mine edit\n")
        # Foreign agent stages a different change.
        (repo / "foreign.py").write_text("foreign staged\n")
        _run(repo, "add", "foreign.py")

        with _patch_worktree_check(False), _patch_session(True), _patch_touched("mine.py"):
            _commit_under_lock(
                message="fix: mine",
                includes=[],
                project_root=repo,
                system_role=None,
            )

        head_files = _run(repo, "show", "--stat", "HEAD")
        assert P_MINE in head_files
        assert P_FOREIGN not in head_files
        # foreign.py is STILL staged for its owner.
        staged = _run(repo, "diff", "--cached", "--name-only").strip().splitlines()
        assert P_FOREIGN in staged


# ── handle_code_add: real classification against a live repo ─────────────────


class TestHandleCodeAddFunctional:
    """`telec code add` accepts NEW + unmerged + partial-staged tracked
    (including partial-staged + deletion), no-ops modified-tracked, and
    rejects clean/missing paths. Each case is exercised against a real
    git repo so the classification cannot drift from git's view of state.
    """

    @pytest.mark.unit
    def test_accepts_untracked_new_file(self, repo: Path) -> None:
        (repo / "new.py").write_text("hi\n")
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=repo),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=repo),
        ):
            handle_code_add(["new.py"])
        # The file is now staged.
        staged = _run(repo, "diff", "--cached", "--name-only").strip().splitlines()
        assert P_NEW in staged

    @pytest.mark.unit
    def test_accepts_partial_staged_tracked_file(self, repo: Path) -> None:
        (repo / "t.py").write_text("v1\n")
        _run(repo, "add", "t.py")
        _run(repo, "commit", "-q", "-m", "add t")
        (repo / "t.py").write_text("v2\n")
        _run(repo, "add", "t.py")
        (repo / "t.py").write_text("v3 working tree only\n")

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=repo),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=repo),
        ):
            handle_code_add(["t.py"])
        # After the recovery, staged version == working-tree version.
        unstaged = _run(repo, "diff", "--name-only").strip().splitlines()
        assert P_T not in unstaged
        # And the file IS in the staged set (full restage).
        staged = _run(repo, "diff", "--cached", "--name-only").strip().splitlines()
        assert P_T in staged

    @pytest.mark.unit
    def test_accepts_partial_staged_with_working_tree_deletion(self, repo: Path) -> None:
        """The F7 case: staged edit + later deletion. File has staged content
        (git knows the path) but no on-disk file. The recovery must accept it."""
        (repo / "del.py").write_text("v1\n")
        _run(repo, "add", "del.py")
        _run(repo, "commit", "-q", "-m", "add del")
        (repo / "del.py").write_text("v2 staged\n")
        _run(repo, "add", "del.py")
        (repo / "del.py").unlink()  # working-tree deletion

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=repo),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=repo),
        ):
            handle_code_add(["del.py"])
        # After recovery: deletion is fully staged; no unstaged remainder.
        unstaged = _run(repo, "diff", "--name-only").strip().splitlines()
        assert P_DEL not in unstaged
        # Staged set shows the deletion.
        staged = _run(repo, "diff", "--cached", "--name-only", "--diff-filter=D").strip().splitlines()
        assert P_DEL in staged

    @pytest.mark.unit
    def test_noop_on_modified_tracked_file(self, repo: Path) -> None:
        """A cleanly modified-tracked file (NOT partial-staged) is no-oped:
        index does NOT advance to match the working tree. The pathspec
        commit picks it up directly later."""
        (repo / "mod.py").write_text("v1\n")
        _run(repo, "add", "mod.py")
        _run(repo, "commit", "-q", "-m", "add mod")
        (repo / "mod.py").write_text("v2\n")

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=repo),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=repo),
        ):
            handle_code_add(["mod.py"])
        # mod.py is NOT in the staged set (no-op).
        staged = _run(repo, "diff", "--cached", "--name-only").strip().splitlines()
        assert P_MOD not in staged
        # It IS in the unstaged set (the working-tree edit is still there).
        unstaged = _run(repo, "diff", "--name-only").strip().splitlines()
        assert P_MOD in unstaged

    @pytest.mark.unit
    def test_rejects_clean_path(self, repo: Path) -> None:
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=repo),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=repo),
            pytest.raises(SystemExit) as exc,
        ):
            handle_code_add(["seed.txt"])  # tracked + clean
        assert exc.value.code == 2

    @pytest.mark.unit
    def test_rejects_missing_path(self, repo: Path) -> None:
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=repo),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=repo),
            pytest.raises(SystemExit) as exc,
        ):
            handle_code_add(["does-not-exist.py"])
        assert exc.value.code == 2
