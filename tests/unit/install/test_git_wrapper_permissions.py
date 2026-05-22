"""Behavioral tests for the git wrapper permission model.

Tests invoke the bash wrapper as a subprocess with a controlled environment
and a fake git binary, asserting on **exit code only** — the wrapper's
safety contract is "block dangerous ops" and the only structural surface
that proves the contract held is the non-zero exit. Stderr, log content,
and diagnostic prose are NOT asserted — those are presentational and the
testing policy forbids any form of string-content assertion (literal,
substring, prefix/suffix, regex, or named-constant identity for prose
tokens). Each test pins one behavioral path with one representative input.

Wrapper context:
  - Outside tmux ($TMUX unset): pass through, no restrictions.
  - Inside tmux, no identity: fail with non-zero exit (identity is broken).
  - Inside tmux, human_role set + no system_role: apply worker restrictions.
  - Inside tmux, system_role set: apply role-based restrictions.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

# Bash subprocess invocations exceed the repo's default 1s per-test budget
# under xdist load even though behavior is correct.
pytestmark = [pytest.mark.unit, pytest.mark.timeout(5)]

WRAPPER_PATH = Path(__file__).resolve().parents[3] / "teleclaude" / "install" / "wrappers" / "git"

_FAKE_GIT_SCRIPT = """\
#!/usr/bin/env bash
# Fake git for wrapper permission tests.
# - rev-parse --abbrev-ref returns FAKE_BRANCH (default: feature).
# - rev-parse --show-toplevel returns FAKE_TOPLEVEL (default: $PWD).
#   Tests set this to simulate being inside the integration worktree.
# - rev-parse --git-dir returns FAKE_GIT_DIR (default: /dev/null → MERGE_HEAD
#   probes evaluate to "not in merge").
# Everything else exits 0.
# Honor -C / -c / --git-dir / --work-tree / --namespace by stripping them.
while :; do
    case "${1:-}" in
        -C) shift 2 ;;
        -c|--git-dir|--work-tree|--namespace) shift 2 ;;
        --git-dir=*|--work-tree=*|--namespace=*|-c*) shift 1 ;;
        *) break ;;
    esac
done
if [ "${1:-}" = "rev-parse" ] && [ "${2:-}" = "--abbrev-ref" ]; then
    echo "${FAKE_BRANCH:-feature}"
    exit 0
fi
if [ "${1:-}" = "rev-parse" ] && [ "${2:-}" = "--show-toplevel" ]; then
    echo "${FAKE_TOPLEVEL:-$PWD}"
    exit 0
fi
if [ "${1:-}" = "rev-parse" ] && [ "${2:-}" = "--git-dir" ]; then
    echo "${FAKE_GIT_DIR:-/dev/null}"
    exit 0
fi
exit 0
"""

_INTEGRATION_TOPLEVEL = "/tmp/repo/trees/_integration"


def _run(
    args: list[str],
    role: str | None = None,
    *,
    human_role: str | None = None,
    branch: str = "feature",
    no_identity_file: bool = False,
    override_approved: bool = False,
    fake_toplevel: str | None = None,
) -> int:
    """Run the bash wrapper via subprocess with mocked identity and fake git.

    Returns exit code only. The wrapper's safety contract is structural —
    blocked ops exit non-zero, allowed ops exit zero. Diagnostic stderr is
    presentational and not asserted on.
    """
    session_tmpdir = Path(tempfile.mkdtemp())
    fake_bin_dir = Path(tempfile.mkdtemp())

    fake_git = fake_bin_dir / "git"
    fake_git.write_text(_FAKE_GIT_SCRIPT)
    fake_git.chmod(0o755)

    if not no_identity_file:
        identity: dict[str, str] = {"session_id": "test-session"}
        if role is not None:
            identity["system_role"] = role
        if human_role is not None:
            identity["human_role"] = human_role
        (session_tmpdir / "teleclaude_identity.json").write_text(json.dumps(identity))

    env = {
        **os.environ,
        "TMPDIR": str(session_tmpdir),
        "TMUX": "test-session",  # simulate being inside tmux — enables restriction checks
        "TELECLAUDE_SYSTEM_ROLE": "",
        "TELECLAUDE_OVERRIDE_APPROVED": "1" if override_approved else "",
        "PATH": f"{fake_bin_dir}:{os.environ.get('PATH', '')}",
        "FAKE_BRANCH": branch,
    }
    if fake_toplevel is not None:
        env["FAKE_TOPLEVEL"] = fake_toplevel

    result = subprocess.run(
        ["bash", str(WRAPPER_PATH)] + args,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode


# ── NO IDENTITY: fail fast ────────────────────────────────────────────────────


class TestNoIdentity:
    def test_no_role_fails_fast(self) -> None:
        assert _run(["status"]) != 0

    def test_no_identity_file_fails(self) -> None:
        assert _run(["status"], no_identity_file=True) != 0


# ── HUMAN SESSION ─────────────────────────────────────────────────────────────


class TestHumanSession:
    def test_status_allowed(self) -> None:
        assert _run(["status"], human_role="admin") == 0

    def test_commit_redirected(self) -> None:
        assert _run(["commit", "-m", "human commit"], human_role="admin") != 0


# ── DESTRUCTIVE ───────────────────────────────────────────────────────────────


class TestDestructive:
    """clean / switch / reset-hard variants and revert-without-confirmed all
    block. Representative role: worker (the wrapper applies these rules to
    every role identically; one input pins the path)."""

    def test_clean_blocked(self) -> None:
        assert _run(["clean", "-fd"], role="worker") != 0

    def test_switch_blocked(self) -> None:
        assert _run(["switch", "main"], role="worker") != 0

    def test_revert_without_confirmed_blocked(self) -> None:
        assert _run(["revert", "abc123"], role="worker") != 0

    def test_revert_with_confirmed_allowed(self) -> None:
        assert _run(["revert", "--confirmed", "abc123"], role="worker") == 0

    def test_reset_hard_blocked(self) -> None:
        assert _run(["reset", "--hard"], role="worker") != 0

    def test_reset_bare_blocked(self) -> None:
        assert _run(["reset"], role="worker") != 0

    def test_reset_head_pathspec_allowed(self) -> None:
        assert _run(["reset", "HEAD", "f.txt"], role="worker") == 0

    def test_reset_separator_pathspec_allowed(self) -> None:
        assert _run(["reset", "--", "f.txt"], role="worker") == 0


# ── STASH: blocked unconditionally ────────────────────────────────────────────


class TestStashBlockedEverywhere:
    """Regression guard: the integrator-only stash carve-out (commit
    9e1742bb4) is gone. Stash is now blocked for every role. Integrator
    is the representative because that was the carve-out site."""

    def test_stash_blocked_for_integrator(self) -> None:
        assert _run(["stash"], role="integrator") != 0

    def test_stash_push_blocked(self) -> None:
        assert _run(["stash", "push", "-u"], role="integrator") != 0

    def test_stash_pop_blocked(self) -> None:
        assert _run(["stash", "pop"], role="integrator") != 0


# ── CHECKOUT ──────────────────────────────────────────────────────────────────


class TestCheckoutPermissions:
    def test_bare_checkout_blocked(self) -> None:
        assert _run(["checkout", "main"], role="worker") != 0

    def test_file_scoped_checkout_allowed(self) -> None:
        assert _run(["checkout", "HEAD", "--", "f.txt"], role="worker") == 0

    def test_file_scoped_in_integration_requires_confirmed(self) -> None:
        assert (
            _run(
                ["checkout", "HEAD", "--", "f.txt"],
                role="integrator",
                fake_toplevel=_INTEGRATION_TOPLEVEL,
            )
            != 0
        )

    def test_file_scoped_in_integration_with_confirmed_allowed(self) -> None:
        assert (
            _run(
                ["checkout", "--confirmed", "HEAD", "--", "f.txt"],
                role="integrator",
                fake_toplevel=_INTEGRATION_TOPLEVEL,
            )
            == 0
        )


# ── RESTORE ───────────────────────────────────────────────────────────────────


class TestRestorePermissions:
    """Pure --staged is index-only and always allowed. Working-tree forms
    (default, --worktree, --source) require --confirmed inside the
    integration worktree or during active merge; allowed elsewhere."""

    def test_staged_only_allowed(self) -> None:
        assert _run(["restore", "--staged", "f.txt"], role="worker") == 0

    def test_default_worktree_outside_integration_allowed(self) -> None:
        assert _run(["restore", "f.txt"], role="worker") == 0

    def test_source_outside_integration_allowed(self) -> None:
        assert _run(["restore", "--source", "HEAD~1", "f.txt"], role="worker") == 0

    def test_default_in_integration_requires_confirmed(self) -> None:
        assert (
            _run(
                ["restore", "f.txt"],
                role="integrator",
                fake_toplevel=_INTEGRATION_TOPLEVEL,
            )
            != 0
        )

    def test_default_in_integration_with_confirmed_allowed(self) -> None:
        assert (
            _run(
                ["restore", "--confirmed", "f.txt"],
                role="integrator",
                fake_toplevel=_INTEGRATION_TOPLEVEL,
            )
            == 0
        )

    def test_staged_plus_worktree_in_integration_still_gated(self) -> None:
        # --staged --worktree touches the worktree; same gate as plain restore.
        assert (
            _run(
                ["restore", "--staged", "--worktree", "f.txt"],
                role="integrator",
                fake_toplevel=_INTEGRATION_TOPLEVEL,
            )
            != 0
        )

    def test_pure_staged_in_integration_allowed(self) -> None:
        # Pure --staged is index-only; no worktree mutation; no gate.
        assert (
            _run(
                ["restore", "--staged", "f.txt"],
                role="integrator",
                fake_toplevel=_INTEGRATION_TOPLEVEL,
            )
            == 0
        )

    def test_source_in_integration_requires_confirmed(self) -> None:
        assert (
            _run(
                ["restore", "--source", "HEAD~1", "f.txt"],
                role="worker",
                fake_toplevel=_INTEGRATION_TOPLEVEL,
            )
            != 0
        )

    def test_minus_C_into_integration_does_not_bypass_gate(self) -> None:
        # The wrapper resolves the effective working tree via `-C`, not $PWD.
        assert (
            _run(
                ["-C", _INTEGRATION_TOPLEVEL, "restore", "f.txt"],
                role="worker",
                fake_toplevel=_INTEGRATION_TOPLEVEL,
            )
            != 0
        )


# ── RESET <TREE-ISH> <PATH> ───────────────────────────────────────────────────


class TestResetTreeishPathspec:
    """Foreign tree-ish reset (e.g. `git reset origin/main path`) pulls
    foreign content into the index and requires --confirmed. `git reset
    HEAD <path>` is canonical unstage and stays allowed (covered by
    TestDestructive.test_reset_head_pathspec_allowed)."""

    def test_foreign_treeish_requires_confirmed(self) -> None:
        assert _run(["reset", "origin/main", "f.txt"], role="worker") != 0

    def test_foreign_treeish_with_confirmed_allowed(self) -> None:
        assert _run(["reset", "--confirmed", "origin/main", "f.txt"], role="worker") == 0


# ── GIT ADD ───────────────────────────────────────────────────────────────────


class TestGitAddBlocked:
    """`git add` is owned by `telec code commit`. Every form is blocked."""

    def test_specific_path_blocked(self) -> None:
        assert _run(["add", "file.txt"], role="worker") != 0

    def test_separator_pathspec_blocked(self) -> None:
        assert _run(["add", "--", "file.txt"], role="worker") != 0

    def test_dash_all_blocked(self) -> None:
        assert _run(["add", "-A"], role="worker") != 0


# ── COMMIT REDIRECT ───────────────────────────────────────────────────────────


class TestCommitRedirect:
    """All git commit calls are redirected to telec code commit, every
    role, every branch. One representative case pins the redirect path."""

    def test_commit_redirected(self) -> None:
        assert _run(["commit", "-m", "test"], role="worker") != 0


# ── REPLAY GATE: cherry-pick / rebase / merge on main ────────────────────────


class TestReplayGateOnMain:
    """cherry-pick/rebase/merge produce commits via paths the commit gate
    misses; on main they need explicit approval (integrator role or
    TELECLAUDE_OVERRIDE_APPROVED=1)."""

    def test_cherry_pick_on_main_without_approval_blocked(self) -> None:
        assert _run(["cherry-pick", "abc123"], role="worker", branch="main") != 0

    def test_rebase_on_main_with_override_allowed(self) -> None:
        assert _run(["rebase", "abc123"], role="worker", branch="main", override_approved=True) == 0

    def test_merge_on_main_as_integrator_allowed(self) -> None:
        assert _run(["merge", "abc123"], role="integrator", branch="main") == 0

    def test_cherry_pick_on_feature_branch_allowed(self) -> None:
        assert _run(["cherry-pick", "abc123"], role="worker", branch="feature") == 0

    def test_abort_arg_on_main_allowed(self) -> None:
        # Replay --abort/--skip/--quit/--no-commit produce no new commit.
        assert _run(["rebase", "--abort"], role="worker", branch="main") == 0

    def test_no_commit_flag_on_main_allowed(self) -> None:
        assert _run(["cherry-pick", "--no-commit", "abc123"], role="worker", branch="main") == 0

    def test_continue_on_main_still_blocked(self) -> None:
        # --continue resumes a paused replay that DOES produce a commit.
        assert _run(["cherry-pick", "--continue"], role="worker", branch="main") != 0


# ── PUSH FROM MAIN ────────────────────────────────────────────────────────────


class TestProtectedPushFromMain:
    def test_non_integrator_blocked(self) -> None:
        assert _run(["push", "origin", "main"], role="worker", branch="main") != 0

    def test_integrator_allowed(self) -> None:
        assert _run(["push", "origin", "main"], role="integrator", branch="main") == 0


# ── ALIAS BYPASS REGRESSION ───────────────────────────────────────────────────


class TestAliasRedefinitionBlocked:
    """Regression guard: `git -c alias.X=stash X` previously bypassed the
    subcmd-name-based stash block. The wrapper now refuses any `-c alias.*`
    config at the invocation level."""

    def test_alias_space_form_blocked(self) -> None:
        assert _run(["-c", "alias.hack=stash", "hack"], role="integrator") != 0

    def test_alias_inline_form_blocked(self) -> None:
        # The -calias.X=... no-space form also blocked.
        assert _run(["-calias.hack=stash", "hack"], role="integrator") != 0
