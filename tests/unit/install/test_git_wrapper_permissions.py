# guard: no-companion
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

_FAKE_GIT_SCRIPT = """\
#!/usr/bin/env bash
# Fake git for wrapper permission tests.
# Returns FAKE_BRANCH for branch detection; exits 0 for everything else.
if [ "${1:-}" = "rev-parse" ] && [ "${2:-}" = "--abbrev-ref" ]; then
    echo "${FAKE_BRANCH:-feature}"
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
        "PATH": f"{fake_bin_dir}:{os.environ.get('PATH', '')}",
        "FAKE_BRANCH": branch,
    }

    result = subprocess.run(
        ["bash", str(WRAPPER_PATH)] + args,
        env=env,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stderr


# ── NO IDENTITY: fail fast ────────────────────────────────────────────────────


class TestNoIdentity:
    def test_no_role_fails_fast(self) -> None:
        code, stderr = _run(["status"])
        assert code != 0
        assert "identity is broken" in stderr.lower()

    def test_no_identity_file_fails(self) -> None:
        code, stderr = _run(["status"], no_identity_file=True)
        assert code != 0
        assert "identity is broken" in stderr.lower()


# ── HUMAN SESSION ─────────────────────────────────────────────────────────────


class TestHumanSession:
    def test_human_status_allowed(self) -> None:
        code, _ = _run(["status"], human_role="admin")
        assert code == 0

    def test_human_commit_allowed(self) -> None:
        # Human in tmux gets worker role, which can commit on non-main branch.
        code, _ = _run(["commit", "-m", "human commit"], human_role="admin", branch="feature")
        assert code == 0


# ── DESTRUCTIVE ───────────────────────────────────────────────────────────────


class TestDestructive:
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_restore_blocked(self, role: str) -> None:
        code, stderr = _run(["restore", "file.txt"], role=role)
        assert code != 0
        assert "destructive" in stderr.lower()

    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_clean_blocked(self, role: str) -> None:
        code, stderr = _run(["clean", "-fd"], role=role)
        assert code != 0
        assert "destructive" in stderr.lower()

    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_switch_blocked(self, role: str) -> None:
        code, stderr = _run(["switch", "main"], role=role)
        assert code != 0
        assert "destructive" in stderr.lower()

    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_revert_without_confirmed_blocked(self, role: str) -> None:
        code, stderr = _run(["revert", "abc123"], role=role)
        assert code != 0
        assert "inspection required" in stderr.lower()

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


# ── PROTECTED: stash ──────────────────────────────────────────────────────────


class TestProtectedStash:
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator"])
    def test_non_integrator_blocked(self, role: str) -> None:
        code, stderr = _run(["stash"], role=role)
        assert code != 0
        assert "protected" in stderr.lower()

    def test_integrator_allowed(self) -> None:
        _, stderr = _run(["stash"], role="integrator")
        assert "protected" not in stderr.lower()


# ── PROTECTED: checkout ───────────────────────────────────────────────────────


class TestCheckoutPermissions:
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_bare_checkout_blocked_for_all(self, role: str) -> None:
        code, stderr = _run(["checkout", "main"], role=role)
        assert code != 0
        assert "protected" in stderr.lower()

    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_file_scoped_checkout_allowed_for_all(self, role: str) -> None:
        _, stderr = _run(["checkout", "HEAD", "--", "f.txt"], role=role)
        assert "protected" not in stderr.lower()


# ── PROTECTED: commit on main ─────────────────────────────────────────────────


class TestProtectedCommitOnMain:
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator"])
    def test_non_integrator_blocked(self, role: str) -> None:
        code, _ = _run(["commit", "-m", "test"], role=role, branch="main")
        assert code != 0

    def test_integrator_allowed(self) -> None:
        code, _ = _run(["commit", "-m", "test"], role="integrator", branch="main")
        assert code == 0


# ── PROTECTED: push from main ─────────────────────────────────────────────────


class TestProtectedPushFromMain:
    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator"])
    def test_non_integrator_blocked(self, role: str) -> None:
        code, stderr = _run(["push", "origin", "main"], role=role, branch="main")
        assert code != 0
        assert "protected" in stderr.lower()

    def test_integrator_allowed(self) -> None:
        code, _ = _run(["push", "origin", "main"], role="integrator", branch="main")
        assert code == 0


# ── ORCHESTRATOR RESTRICTION ──────────────────────────────────────────────────


class TestOrchestratorRestriction:
    def test_orchestrator_blocked_on_branch(self) -> None:
        code, stderr = _run(["commit", "-m", "test"], role="orchestrator", branch="feature")
        assert code != 0
        assert "orchestrator" in stderr.lower()

    def test_orchestrator_blocked_on_main(self) -> None:
        code, _ = _run(["commit", "-m", "test"], role="orchestrator", branch="main")
        assert code != 0

    def test_worker_allowed_on_branch(self) -> None:
        code, _ = _run(["commit", "-m", "test"], role="worker", branch="feature")
        assert code == 0

    def test_system_allowed_on_branch(self) -> None:
        code, _ = _run(["commit", "-m", "test"], role="system", branch="feature")
        assert code == 0
