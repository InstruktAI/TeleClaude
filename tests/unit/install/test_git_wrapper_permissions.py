"""Behavioral tests for the git wrapper three-tier permission model.

Tests invoke the bash wrapper as a subprocess with a controlled environment
and a fake git binary, asserting on exit code and stderr output.

The wrapper behavior under test:
  - Outside tmux ($TMUX unset): pass through, no restrictions.
  - Inside tmux, no identity: fail with "identity is broken".
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

# The wrapper is exercised via real bash subprocesses, which exceed the repo's
# default 1s per-test budget under xdist load even though behavior is correct.
pytestmark = [pytest.mark.unit, pytest.mark.timeout(5)]

WRAPPER_PATH = Path(__file__).resolve().parents[3] / "teleclaude" / "install" / "wrappers" / "git"

# Named markers for the wrapper's diagnostic vocabulary. The wrapper emits
# these tokens verbatim on the stderr it prints when blocking; the tests
# assert presence of the token, not the surrounding prose. Per the testing
# policy's "String Assertions — One Paradigm", string content assertions
# go through named constants rather than literal substrings.
_DIAG_PROHIBITED = "prohibited"
_DIAG_DESTRUCTIVE = "destructive"
_DIAG_PROTECTED = "protected"
_DIAG_INSPECTION_REQUIRED = "inspection required"
_DIAG_TELEC_CODE_COMMIT = "telec code commit"
_DIAG_IDENTITY_BROKEN = "identity is broken"

_FAKE_GIT_SCRIPT = """\
#!/usr/bin/env bash
# Fake git for wrapper permission tests.
# - rev-parse --abbrev-ref returns FAKE_BRANCH (default: feature).
# - rev-parse --show-toplevel returns FAKE_TOPLEVEL (default: $PWD).
#   Tests set this to simulate being inside the integration worktree.
# - rev-parse --git-dir returns FAKE_GIT_DIR (default: empty → MERGE_HEAD
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


def _run(
    args: list[str],
    role: str | None = None,
    *,
    human_role: str | None = None,
    branch: str = "feature",
    no_identity_file: bool = False,
    override_approved: bool = False,
    fake_toplevel: str | None = None,
) -> tuple[int, str]:
    """Run the bash wrapper via subprocess with mocked identity and fake git.

    Returns (exit_code, stderr).
    TMUX is set to simulate being inside a tmux session so restrictions apply.
    """
    session_tmpdir = Path(tempfile.mkdtemp())
    fake_bin_dir = Path(tempfile.mkdtemp())

    # Fake git: handles rev-parse for branch detection, exits 0 for everything else.
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
    return result.returncode, result.stderr


# ── NO IDENTITY: fail fast ────────────────────────────────────────────────────


class TestNoIdentity:
    def test_no_role_fails_fast(self) -> None:
        code, stderr = _run(["status"])
        assert code != 0
        assert _DIAG_IDENTITY_BROKEN in stderr.lower()

    def test_no_identity_file_fails(self) -> None:
        code, stderr = _run(["status"], no_identity_file=True)
        assert code != 0
        assert _DIAG_IDENTITY_BROKEN in stderr.lower()


# ── HUMAN SESSION ─────────────────────────────────────────────────────────────


class TestHumanSession:
    def test_human_status_allowed(self) -> None:
        code, _ = _run(["status"], human_role="admin")
        assert code == 0

    def test_human_commit_redirected(self) -> None:
        # All git commit calls are redirected to telec code commit.
        code, stderr = _run(["commit", "-m", "human commit"], human_role="admin", branch="feature")
        assert code != 0
        assert _DIAG_TELEC_CODE_COMMIT in stderr


# ── DESTRUCTIVE ───────────────────────────────────────────────────────────────


class TestDestructive:
    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_clean_blocked(self, role: str) -> None:
        code, stderr = _run(["clean", "-fd"], role=role)
        assert code != 0
        assert _DIAG_DESTRUCTIVE in stderr.lower()

    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_switch_blocked(self, role: str) -> None:
        code, stderr = _run(["switch", "main"], role=role)
        assert code != 0
        assert _DIAG_DESTRUCTIVE in stderr.lower()

    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_revert_without_confirmed_blocked(self, role: str) -> None:
        code, stderr = _run(["revert", "abc123"], role=role)
        assert code != 0
        assert _DIAG_INSPECTION_REQUIRED in stderr.lower()

    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_reset_hard_blocked(self, role: str) -> None:
        code, _ = _run(["reset", "--hard"], role=role)
        assert code != 0

    def test_reset_bare_blocked(self) -> None:
        code, _ = _run(["reset"], role="worker")
        assert code != 0

    def test_reset_pathspec_allowed(self) -> None:
        code, _ = _run(["reset", "HEAD", "f.txt"], role="worker")
        assert code == 0

    def test_reset_separator_pathspec_allowed(self) -> None:
        code, _ = _run(["reset", "--", "f.txt"], role="worker")
        assert code == 0


# ── DESTRUCTIVE: stash blocked unconditionally ────────────────────────────────


class TestStashBlockedEverywhere:
    """`git stash` is blocked for every role, with no override. Stash captures
    every dirty file in the worktree it runs in — no pathspec granularity —
    so it lifts other agents' WIP in a multi-agent repo. The integrator's
    documented recovery when repo-root sync finds dirty files is to halt and
    surface to the human; stash is never the sanctioned tool."""

    def test_worker_blocked(self) -> None:
        code, stderr = _run(["stash"], role="worker")
        assert code != 0
        assert _DIAG_PROHIBITED in stderr.lower()

    def test_system_blocked(self) -> None:
        code, stderr = _run(["stash"], role="system")
        assert code != 0
        assert _DIAG_PROHIBITED in stderr.lower()

    def test_orchestrator_blocked(self) -> None:
        code, stderr = _run(["stash"], role="orchestrator")
        assert code != 0
        assert _DIAG_PROHIBITED in stderr.lower()

    def test_integrator_blocked(self) -> None:
        # Regression guard: the integrator carve-out introduced by
        # commit 9e1742bb4 (March 20, 2026) is gone.
        code, stderr = _run(["stash"], role="integrator")
        assert code != 0
        assert _DIAG_PROHIBITED in stderr.lower()

    def test_human_blocked(self) -> None:
        code, stderr = _run(["stash"], human_role="admin")
        assert code != 0
        assert _DIAG_PROHIBITED in stderr.lower()

    def test_stash_push_blocked(self) -> None:
        code, stderr = _run(["stash", "push", "-u"], role="integrator")
        assert code != 0
        assert _DIAG_PROHIBITED in stderr.lower()

    def test_stash_pop_blocked(self) -> None:
        code, stderr = _run(["stash", "pop"], role="integrator")
        assert code != 0
        assert _DIAG_PROHIBITED in stderr.lower()


# ── PROTECTED: checkout ───────────────────────────────────────────────────────


class TestCheckoutPermissions:
    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_bare_checkout_blocked_for_all(self, role: str) -> None:
        code, stderr = _run(["checkout", "main"], role=role)
        assert code != 0
        assert _DIAG_PROTECTED in stderr.lower()

    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_file_scoped_checkout_allowed_for_all(self, role: str) -> None:
        _, stderr = _run(["checkout", "HEAD", "--", "f.txt"], role=role)
        assert "protected" not in stderr.lower()

    def test_file_scoped_checkout_inside_integration_requires_confirmed(self) -> None:
        code, stderr = _run(
            ["checkout", "HEAD", "--", "f.txt"],
            role="integrator",
            fake_toplevel="/tmp/repo/trees/_integration",
        )
        assert code != 0
        assert _DIAG_INSPECTION_REQUIRED in stderr.lower()

    def test_file_scoped_checkout_inside_integration_with_confirmed_allowed(self) -> None:
        code, _ = _run(
            ["checkout", "--confirmed", "HEAD", "--", "f.txt"],
            role="integrator",
            fake_toplevel="/tmp/repo/trees/_integration",
        )
        assert code == 0


# ── CONFIRMED: git restore matrix ─────────────────────────────────────────────


class TestRestorePermissions:
    """`git restore` is no longer blanket-DESTRUCTIVE. Risk surface mirrors
    `git checkout -- <path>` / `git reset -- <path>` / `git checkout <ref>
    -- <path>` and gating follows the same matrix:
      - Pure --staged (index-only): always allowed.
      - Working-tree forms (default, --worktree, --source): allowed outside
        the integration worktree; require --confirmed inside it or during
        an active merge.
    """

    def test_staged_index_only_allowed(self) -> None:
        code, stderr = _run(["restore", "--staged", "f.txt"], role="worker")
        assert code == 0
        assert "destructive" not in stderr.lower()

    def test_worktree_default_allowed_outside_integration(self) -> None:
        code, stderr = _run(["restore", "f.txt"], role="worker")
        assert code == 0
        assert "destructive" not in stderr.lower()

    def test_staged_plus_worktree_outside_integration_allowed(self) -> None:
        code, _ = _run(["restore", "--staged", "--worktree", "f.txt"], role="worker")
        assert code == 0

    def test_source_outside_integration_allowed(self) -> None:
        code, _ = _run(["restore", "--source", "HEAD~1", "f.txt"], role="worker")
        assert code == 0

    def test_default_inside_integration_requires_confirmed(self) -> None:
        code, stderr = _run(
            ["restore", "f.txt"],
            role="integrator",
            fake_toplevel="/tmp/repo/trees/_integration",
        )
        assert code != 0
        assert _DIAG_INSPECTION_REQUIRED in stderr.lower()

    def test_default_inside_integration_with_confirmed_allowed(self) -> None:
        code, _ = _run(
            ["restore", "--confirmed", "f.txt"],
            role="integrator",
            fake_toplevel="/tmp/repo/trees/_integration",
        )
        assert code == 0

    def test_staged_plus_worktree_inside_integration_requires_confirmed(self) -> None:
        # --staged --worktree still mutates the worktree; same gate as plain restore.
        code, stderr = _run(
            ["restore", "--staged", "--worktree", "f.txt"],
            role="integrator",
            fake_toplevel="/tmp/repo/trees/_integration",
        )
        assert code != 0
        assert _DIAG_INSPECTION_REQUIRED in stderr.lower()

    def test_pure_staged_inside_integration_allowed(self) -> None:
        # Pure --staged is index-only; no working-tree mutation; no gate.
        code, _ = _run(
            ["restore", "--staged", "f.txt"],
            role="integrator",
            fake_toplevel="/tmp/repo/trees/_integration",
        )
        assert code == 0

    def test_source_inside_integration_requires_confirmed(self) -> None:
        code, stderr = _run(
            ["restore", "--source", "HEAD~1", "f.txt"],
            role="worker",
            fake_toplevel="/tmp/repo/trees/_integration",
        )
        assert code != 0
        assert _DIAG_INSPECTION_REQUIRED in stderr.lower()

    def test_minus_C_into_integration_does_not_bypass_gate(self) -> None:
        # The wrapper resolves the effective working tree via `-C`, not $PWD.
        code, stderr = _run(
            ["-C", "/tmp/repo/trees/_integration", "restore", "f.txt"],
            role="worker",
            fake_toplevel="/tmp/repo/trees/_integration",
        )
        assert code != 0
        assert _DIAG_INSPECTION_REQUIRED in stderr.lower()


# ── CONFIRMED: git reset tree-ish pathspec ────────────────────────────────────


class TestResetTreeishPathspec:
    """`git reset HEAD <path>` is canonical unstage and stays allowed.
    `git reset <foreign-ref> <path>` pulls from a foreign tree-ish — same
    risk surface as `git checkout <ref> -- <path>` — and now requires
    --confirmed."""

    def test_reset_head_pathspec_allowed(self) -> None:
        code, _ = _run(["reset", "HEAD", "f.txt"], role="worker")
        assert code == 0

    def test_reset_foreign_treeish_pathspec_requires_confirmed(self) -> None:
        code, stderr = _run(["reset", "origin/main", "f.txt"], role="worker")
        assert code != 0
        assert _DIAG_INSPECTION_REQUIRED in stderr.lower()

    def test_reset_foreign_treeish_with_confirmed_allowed(self) -> None:
        code, _ = _run(
            ["reset", "--confirmed", "origin/main", "f.txt"],
            role="worker",
        )
        assert code == 0


# ── GIT ADD: blocked for all agent roles ──────────────────────────────────────


class TestGitAddBlocked:
    """`git add` is owned by `telec code commit`. Agents have no use case for
    invoking it directly; the wrapper blocks every form and teaches the
    sealed alternative."""

    def test_blocked_specific_path(self) -> None:
        code, stderr = _run(["add", "file.txt"], role="worker", branch="feature")
        assert code != 0
        assert _DIAG_TELEC_CODE_COMMIT in stderr

    def test_blocked_with_separator_pathspec(self) -> None:
        code, stderr = _run(["add", "--", "file.txt"], role="worker", branch="feature")
        assert code != 0
        assert _DIAG_TELEC_CODE_COMMIT in stderr

    def test_blocked_dash_all(self) -> None:
        code, stderr = _run(["add", "-A"], role="worker", branch="feature")
        assert code != 0
        assert _DIAG_TELEC_CODE_COMMIT in stderr

    def test_blocked_on_main(self) -> None:
        code, stderr = _run(["add", "file.txt"], role="worker", branch="main")
        assert code != 0
        assert _DIAG_TELEC_CODE_COMMIT in stderr

    def test_blocked_for_integrator(self) -> None:
        """Integrator no longer needs `git add` — `--include` covers
        conflict resolution. Block applies to every agent role."""
        code, stderr = _run(["add", "resolved.txt"], role="integrator", branch="main")
        assert code != 0
        assert _DIAG_TELEC_CODE_COMMIT in stderr

    def test_blocked_for_human_session(self) -> None:
        code, stderr = _run(["add", "file.txt"], human_role="admin", branch="feature")
        assert code != 0
        assert _DIAG_TELEC_CODE_COMMIT in stderr


# ── COMMIT REDIRECT ───────────────────────────────────────────────────────────


class TestCommitRedirect:
    """All git commit calls are redirected to telec code commit."""

    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_all_roles_redirected_on_branch(self, role: str) -> None:
        code, stderr = _run(["commit", "-m", "test"], role=role, branch="feature")
        assert code != 0
        assert _DIAG_TELEC_CODE_COMMIT in stderr

    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_all_roles_redirected_on_main(self, role: str) -> None:
        code, stderr = _run(["commit", "-m", "test"], role=role, branch="main")
        assert code != 0
        assert _DIAG_TELEC_CODE_COMMIT in stderr

    def test_human_session_redirected(self) -> None:
        code, stderr = _run(["commit", "-m", "test"], human_role="admin", branch="main")
        assert code != 0
        assert _DIAG_TELEC_CODE_COMMIT in stderr


# ── REPLAY GATE: cherry-pick / rebase / merge on main ────────────────────────


class TestReplayGateOnMain:
    """cherry-pick/rebase/merge produce commits via paths the commit gate
    misses; on main they need explicit approval."""

    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("subcmd", ["cherry-pick", "rebase", "merge"])
    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator"])
    def test_blocked_on_main_without_approval(self, subcmd: str, role: str) -> None:
        code, stderr = _run([subcmd, "abc123"], role=role, branch="main")
        assert code != 0
        assert "approval gate" in stderr.lower()

    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("subcmd", ["cherry-pick", "rebase", "merge"])
    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_allowed_on_main_with_approval(self, subcmd: str, role: str) -> None:
        code, _ = _run([subcmd, "abc123"], role=role, branch="main", override_approved=True)
        assert code == 0

    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("subcmd", ["cherry-pick", "rebase", "merge"])
    def test_integrator_bypasses_gate_on_main(self, subcmd: str) -> None:
        """Integrator role merges to main without exporting TELECLAUDE_OVERRIDE_APPROVED."""
        code, _ = _run([subcmd, "abc123"], role="integrator", branch="main")
        assert code == 0

    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("subcmd", ["cherry-pick", "rebase", "merge"])
    def test_allowed_on_feature_branch_without_approval(self, subcmd: str) -> None:
        code, _ = _run([subcmd, "abc123"], role="worker", branch="feature")
        assert code == 0

    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("subcmd", ["cherry-pick", "rebase", "merge"])
    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("noop_arg", ["--abort", "--skip", "--quit"])
    def test_noop_args_allowed_on_main(self, subcmd: str, noop_arg: str) -> None:
        code, _ = _run([subcmd, noop_arg], role="worker", branch="main")
        assert code == 0

    def test_no_commit_flag_allowed_on_main(self) -> None:
        code, _ = _run(["cherry-pick", "--no-commit", "abc123"], role="worker", branch="main")
        assert code == 0

    def test_continue_blocked_on_main(self) -> None:
        code, stderr = _run(["cherry-pick", "--continue"], role="worker", branch="main")
        assert code != 0
        assert "approval gate" in stderr.lower()


# ── PROTECTED: push from main ─────────────────────────────────────────────────


class TestProtectedPushFromMain:
    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator"])
    def test_non_integrator_blocked(self, role: str) -> None:
        code, stderr = _run(["push", "origin", "main"], role=role, branch="main")
        assert code != 0
        assert _DIAG_PROTECTED in stderr.lower()

    def test_integrator_allowed(self) -> None:
        code, _ = _run(["push", "origin", "main"], role="integrator", branch="main")
        assert code == 0


# ── ORCHESTRATOR RESTRICTION ──────────────────────────────────────────────────
# Commit-level orchestrator restriction moved to telec code commit.
# Wrapper redirects all commits; orchestrator-specific tests in TestCommitRedirect.


# ── ALIAS BYPASS REGRESSION ───────────────────────────────────────────────────


_DIAG_ALIAS_REDEFINITION = "redefine git subcommands"


class TestAliasRedefinitionBlocked:
    """Regression guard: `git -c alias.X=stash X` previously bypassed the
    subcmd-name-based stash block because the wrapper parsed `X` as the
    subcommand. The wrapper now refuses any `-c alias.*` config at the
    invocation level."""

    def test_alias_redefining_stash_blocked_for_integrator(self) -> None:
        code, stderr = _run(
            ["-c", "alias.hack=stash", "hack"],
            role="integrator",
        )
        assert code != 0
        assert _DIAG_ALIAS_REDEFINITION in stderr.lower()

    def test_alias_redefining_stash_blocked_for_worker(self) -> None:
        code, stderr = _run(
            ["-c", "alias.hack=stash", "hack"],
            role="worker",
        )
        assert code != 0
        assert _DIAG_ALIAS_REDEFINITION in stderr.lower()

    def test_alias_inline_form_blocked(self) -> None:
        # The -calias.X=... inline form (no space) also blocked.
        code, stderr = _run(
            ["-calias.hack=stash", "hack"],
            role="integrator",
        )
        assert code != 0
        assert _DIAG_ALIAS_REDEFINITION in stderr.lower()
