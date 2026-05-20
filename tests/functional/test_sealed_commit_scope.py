"""Functional tests for the sealed-commit pipeline against real git repos.

These tests exercise:
  * ``resolve_workspace_scope_resolution`` — scope is strictly
    (touched ∩ dirty); foreign deletions DO NOT leak.
  * ``_commit_under_lock`` — the full commit flow against a live repo:
    pathspec boundary, untracked-not-staged drop, ``--include``
    declarations, partial-staging guard, unmerged-index handling.
  * ``handle_code_add`` — accepts NEW + unmerged + partial-staged tracked
    (including partial-staged + deletion); no-ops modified-tracked;
    rejects clean and missing paths.

Mocking is restricted to the transcript-touched signal
(``_resolve_session_touched_paths`` / ``collect_session_touched_files``),
which would otherwise require a fully wired daemon. Everything else —
git state, file system, staging, commit pathspec — is real.

Assertions parse git's structured output into path sets and compare set
membership/equality. Raw substring matching is forbidden by the testing
policy (snapshot-testing guardrail).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

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

# Functional, not unit: real subprocess git + real fs. Bump the per-test
# timeout because each test runs many git invocations.
pytestmark = [pytest.mark.functional, pytest.mark.timeout(15)]

# Path constants — protocol identifiers (fixture file names) used both
# when writing to disk and when asserting against parsed git output.
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


# ── Real-git helpers ─────────────────────────────────────────────────────────


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


def _committed_paths(repo: Path, ref: str = "HEAD") -> set[str]:
    """Return the set of file paths in the named commit."""
    out = _run(repo, "show", "--no-color", "--name-only", "--format=", ref)
    return {line.strip() for line in out.splitlines() if line.strip()}


def _staged_paths(repo: Path) -> set[str]:
    """Return paths currently in the index (ACMRD)."""
    out = _run(repo, "diff", "--cached", "--name-only", "--diff-filter=ACMRD")
    return {line.strip() for line in out.splitlines() if line.strip()}


def _unstaged_paths(repo: Path) -> set[str]:
    """Return paths with unstaged tracked-file changes (ACMRD)."""
    out = _run(repo, "diff", "--name-only", "--diff-filter=ACMRD")
    return {line.strip() for line in out.splitlines() if line.strip()}


def _untracked_paths(repo: Path) -> set[str]:
    """Return paths git does not yet know about (untracked working-tree files)."""
    out = _run(repo, "ls-files", "--others", "--exclude-standard")
    return {line.strip() for line in out.splitlines() if line.strip()}


def _head_oid(repo: Path) -> str:
    """Return the current HEAD object id for before/after identity comparisons."""
    return _run(repo, "rev-parse", "HEAD").strip()


def _patch_worktree_check(is_worktree: bool):
    return patch("teleclaude.quality.scope.is_worktree", return_value=is_worktree)


def _patch_touched(*paths: str):
    return patch.object(scope_module, "_resolve_session_touched_paths", return_value=tuple(sorted(paths)))


def _patch_session(have: bool = True):
    return patch("teleclaude.quality.scope.get_session_id", return_value="sess-1" if have else "")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repo with a single seed commit."""
    _run(tmp_path, "init", "-q", "-b", "main")
    _run(tmp_path, "config", "user.email", "t@t")
    _run(tmp_path, "config", "user.name", "t")
    (tmp_path / P_SEED).write_text("seed\n")
    _run(tmp_path, "add", P_SEED)
    _run(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


# ── Scope resolution: the foreign-deletion-leak bug ──────────────────────────


class TestScopeForeignDeletionDoesNotLeak:
    """The bug the user reported: agent A deletes foo.py; agent B's
    ``resolve_workspace_scope_resolution`` MUST NOT include foo.py in B's
    ``scoped_dirty_paths`` just because foo.py is deleted globally. Scope
    is strictly (this session's touched paths) ∩ (currently dirty paths).
    """

    def test_foreign_deletion_excluded_from_scope(self, repo: Path) -> None:
        (repo / P_A).write_text("a\n")
        (repo / P_B).write_text("b\n")
        _run(repo, "add", P_A, P_B)
        _run(repo, "commit", "-q", "-m", "add a and b")
        (repo / P_A).unlink()  # agent A's deletion, working-tree only
        (repo / P_B).write_text("b modified by B\n")  # agent B's edit

        with _patch_worktree_check(False), _patch_session(True), _patch_touched(P_B):
            resolution = resolve_workspace_scope_resolution(repo)

        # Scope contains ONLY B's touched file (set equality, not substring).
        assert resolution.kind is WorkspaceScopeKind.SHARED_BRANCH
        assert set(resolution.scoped_dirty_paths) == {P_B}
        # Raw dirty set names both — A.txt deletion lives in working-tree
        # state but is excluded from THIS session's scope.
        dirty = {d.path for d in resolution.dirty_paths}
        assert {P_A, P_B}.issubset(dirty)

    def test_own_deletion_included_when_touched(self, repo: Path) -> None:
        (repo / P_X).write_text("x\n")
        _run(repo, "add", P_X)
        _run(repo, "commit", "-q", "-m", "add x")
        (repo / P_X).unlink()

        with _patch_worktree_check(False), _patch_session(True), _patch_touched(P_X):
            resolution = resolve_workspace_scope_resolution(repo)

        assert set(resolution.scoped_dirty_paths) == {P_X}

    def test_worktree_kind_includes_all_dirty(self, repo: Path) -> None:
        (repo / P_X).write_text("x\n")
        _run(repo, "add", P_X)
        _run(repo, "commit", "-q", "-m", "add x")
        (repo / P_X).unlink()  # not touched by transcript

        with _patch_worktree_check(True), _patch_session(True), _patch_touched():
            resolution = resolve_workspace_scope_resolution(repo)

        assert resolution.kind is WorkspaceScopeKind.WORKTREE
        # Set membership — not substring on the tuple's str repr.
        assert P_X in set(resolution.scoped_dirty_paths)


# ── _check_partial_staging: real git index, real partial state ───────────────


class TestPartialStagingGuard:
    """Run the guard against a live git index in three actual states."""

    def test_partial_staged_in_pathspec_blocks(self, repo: Path) -> None:
        (repo / P_T).write_text("v1\n")
        _run(repo, "add", P_T)
        _run(repo, "commit", "-q", "-m", "add t")
        (repo / P_T).write_text("v2 staged\n")
        _run(repo, "add", P_T)
        (repo / P_T).write_text("v3 unstaged\n")

        with pytest.raises(SystemExit) as exc:
            _check_partial_staging(repo, pathspec=[P_T])
        assert exc.value.code == 1

    def test_partial_staged_outside_pathspec_passes(self, repo: Path) -> None:
        (repo / P_FOREIGN).write_text("v1\n")
        (repo / P_MINE).write_text("v1\n")
        _run(repo, "add", P_FOREIGN, P_MINE)
        _run(repo, "commit", "-q", "-m", "add both")
        (repo / P_FOREIGN).write_text("v2\n")
        _run(repo, "add", P_FOREIGN)
        (repo / P_FOREIGN).write_text("v3\n")  # foreign partial-staged
        (repo / P_MINE).write_text("clean edit\n")  # mine: unstaged only

        # Pathspec is just mine.py — foreign's partial-staging is irrelevant.
        _check_partial_staging(repo, pathspec=[P_MINE])  # must not raise

    def test_clean_pathspec_passes(self, repo: Path) -> None:
        _check_partial_staging(repo, pathspec=[P_SEED])  # must not raise


# ── _commit_under_lock: end-to-end against a real repo ───────────────────────


class TestCommitUnderLockEndToEnd:
    """Full commit flow against a live repo. No git is mocked here — the
    pathspec actually commits, foreign files actually remain in the index,
    and partial-staging is actually detected by `git diff`.
    """

    def test_modified_tracked_commits_via_pathspec_no_staging(self, repo: Path) -> None:
        (repo / P_MINE).write_text("v1\n")
        (repo / P_FOREIGN).write_text("v1\n")
        _run(repo, "add", P_MINE, P_FOREIGN)
        _run(repo, "commit", "-q", "-m", "add both")
        (repo / P_MINE).write_text("mine edited\n")  # my edit
        (repo / P_FOREIGN).unlink()  # someone else's deletion

        with _patch_worktree_check(False), _patch_session(True), _patch_touched(P_MINE):
            _commit_under_lock(
                message="fix: my edit",
                includes=[],
                project_root=repo,
                system_role=None,
            )

        # HEAD touched only mine.py; foreign deletion stayed uncommitted.
        assert _committed_paths(repo) == {P_MINE}
        # foreign.py's deletion is structurally an unstaged-tracked change.
        assert P_FOREIGN in _unstaged_paths(repo)

    def test_untracked_new_file_in_scope_is_dropped(self, repo: Path) -> None:
        (repo / P_MINE).write_text("v1\n")
        _run(repo, "add", P_MINE)
        _run(repo, "commit", "-q", "-m", "add mine")
        (repo / P_MINE).write_text("mine edited\n")
        (repo / P_NEW).write_text("scratch I created\n")

        with _patch_worktree_check(False), _patch_session(True), _patch_touched(P_MINE, P_NEW):
            _commit_under_lock(
                message="fix: my edit",
                includes=[],
                project_root=repo,
                system_role=None,
            )

        assert _committed_paths(repo) == {P_MINE}
        # The new file is structurally an untracked working-tree file.
        assert P_NEW in _untracked_paths(repo)

    def test_untracked_new_file_with_include_is_committed(self, repo: Path) -> None:
        (repo / P_MINE).write_text("v1\n")
        _run(repo, "add", P_MINE)
        _run(repo, "commit", "-q", "-m", "add mine")
        (repo / P_MINE).write_text("mine edited\n")
        (repo / P_EXTRA).write_text("intentional new\n")

        with _patch_worktree_check(False), _patch_session(True), _patch_touched(P_MINE, P_EXTRA):
            _commit_under_lock(
                message="fix: mine plus extra",
                includes=[P_EXTRA],
                project_root=repo,
                system_role=None,
            )

        assert _committed_paths(repo) == {P_MINE, P_EXTRA}

    def test_partial_staged_file_in_pathspec_blocks_commit(self, repo: Path) -> None:
        (repo / P_MINE).write_text("v1\n")
        _run(repo, "add", P_MINE)
        _run(repo, "commit", "-q", "-m", "add mine")
        (repo / P_MINE).write_text("v2 staged\n")
        _run(repo, "add", P_MINE)
        (repo / P_MINE).write_text("v3 unstaged\n")

        # Capture HEAD before the blocked commit so we can prove it did
        # not advance via object-id identity (no string-content compare).
        head_before = _head_oid(repo)

        with (
            _patch_worktree_check(False),
            _patch_session(True),
            _patch_touched(P_MINE),
            pytest.raises(SystemExit) as exc,
        ):
            _commit_under_lock(
                message="fix: mine",
                includes=[],
                project_root=repo,
                system_role=None,
            )
        assert exc.value.code == 1
        # HEAD object id is identical → no new commit landed.
        assert _head_oid(repo) == head_before

    def test_foreign_staged_file_not_swept_by_pathspec(self, repo: Path) -> None:
        (repo / P_MINE).write_text("v1\n")
        (repo / P_FOREIGN).write_text("v1\n")
        _run(repo, "add", P_MINE, P_FOREIGN)
        _run(repo, "commit", "-q", "-m", "add both")
        (repo / P_MINE).write_text("mine edit\n")
        (repo / P_FOREIGN).write_text("foreign staged\n")
        _run(repo, "add", P_FOREIGN)

        with _patch_worktree_check(False), _patch_session(True), _patch_touched(P_MINE):
            _commit_under_lock(
                message="fix: mine",
                includes=[],
                project_root=repo,
                system_role=None,
            )

        assert _committed_paths(repo) == {P_MINE}
        # foreign.py is STILL staged for its owner — pathspec did not sweep.
        assert P_FOREIGN in _staged_paths(repo)


# ── handle_code_add: real classification against a live repo ─────────────────


class TestHandleCodeAddFunctional:
    """`telec code add` accepts NEW + unmerged + partial-staged tracked
    (including partial-staged + deletion), no-ops modified-tracked, and
    rejects clean/missing paths.
    """

    def test_accepts_untracked_new_file(self, repo: Path) -> None:
        (repo / P_NEW).write_text("hi\n")
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=repo),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=repo),
        ):
            handle_code_add([P_NEW])
        assert P_NEW in _staged_paths(repo)

    def test_accepts_partial_staged_tracked_file(self, repo: Path) -> None:
        (repo / P_T).write_text("v1\n")
        _run(repo, "add", P_T)
        _run(repo, "commit", "-q", "-m", "add t")
        (repo / P_T).write_text("v2\n")
        _run(repo, "add", P_T)
        (repo / P_T).write_text("v3 working tree only\n")

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=repo),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=repo),
        ):
            handle_code_add([P_T])
        # After recovery: file is in staged set, NOT in unstaged set.
        assert P_T in _staged_paths(repo)
        assert P_T not in _unstaged_paths(repo)

    def test_accepts_partial_staged_with_working_tree_deletion(self, repo: Path) -> None:
        """The F7 case: staged edit + later deletion."""
        (repo / P_DEL).write_text("v1\n")
        _run(repo, "add", P_DEL)
        _run(repo, "commit", "-q", "-m", "add del")
        (repo / P_DEL).write_text("v2 staged\n")
        _run(repo, "add", P_DEL)
        (repo / P_DEL).unlink()  # working-tree deletion

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=repo),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=repo),
        ):
            handle_code_add([P_DEL])
        # Deletion is fully staged; no unstaged remainder.
        assert P_DEL not in _unstaged_paths(repo)
        deletions = {
            line.strip()
            for line in _run(repo, "diff", "--cached", "--name-only", "--diff-filter=D").splitlines()
            if line.strip()
        }
        assert P_DEL in deletions

    def test_noop_on_modified_tracked_file(self, repo: Path) -> None:
        (repo / P_MOD).write_text("v1\n")
        _run(repo, "add", P_MOD)
        _run(repo, "commit", "-q", "-m", "add mod")
        (repo / P_MOD).write_text("v2\n")

        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=repo),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=repo),
        ):
            handle_code_add([P_MOD])
        # No-op: NOT in staged set; IS in unstaged set (working-tree change).
        assert P_MOD not in _staged_paths(repo)
        assert P_MOD in _unstaged_paths(repo)

    def test_rejects_clean_path(self, repo: Path) -> None:
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=repo),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=repo),
            pytest.raises(SystemExit) as exc,
        ):
            handle_code_add([P_SEED])
        assert exc.value.code == 2

    def test_rejects_missing_path(self, repo: Path) -> None:
        with (
            patch("teleclaude.cli.telec.handlers.code.resolve_workspace_root", return_value=repo),
            patch("teleclaude.cli.telec.handlers.code.resolve_invocation_cwd", return_value=repo),
            pytest.raises(SystemExit) as exc,
        ):
            handle_code_add([P_MISSING])
        assert exc.value.code == 2
