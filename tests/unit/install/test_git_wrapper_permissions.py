# guard: no-companion
"""Behavioral tests for the git wrapper three-tier permission model.

Three tiers:
  DESTRUCTIVE  — blocked for all roles, no override
  PROTECTED    — integrator only (stash), integrator+system (checkout, commit/push on main)
  RESTRICTED   — orchestrator cannot commit on any branch

Roles: worker (default), system, orchestrator, integrator.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

WRAPPER = Path(__file__).resolve().parents[3] / "teleclaude" / "install" / "wrappers" / "git"


def _run_wrapper(args: list[str], role: str | None = None, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run the git wrapper with given args and role, capturing output."""
    env = os.environ.copy()
    if role is not None:
        env["TELECLAUDE_SYSTEM_ROLE"] = role
    else:
        env.pop("TELECLAUDE_SYSTEM_ROLE", None)
    # Strip ~/.teleclaude/bin from PATH so the wrapper finds real git, not the
    # installed (potentially stale) copy of itself.
    teleclaude_bin = str(Path.home() / ".teleclaude" / "bin")
    env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if p != teleclaude_bin)
    return subprocess.run(
        ["bash", str(WRAPPER)] + args,
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=5,
    )


def _make_main_repo(tmp_path: Path) -> Path:
    """Create a git repo on branch 'main' with staged changes ready to commit."""
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], capture_output=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True)
    (tmp_path / "f.txt").write_text("y")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
    return tmp_path


def _make_branch_repo(tmp_path: Path, branch: str = "feature") -> Path:
    """Create a git repo on a non-main branch with staged changes."""
    subprocess.run(["git", "init", "-b", branch, str(tmp_path)], capture_output=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True)
    (tmp_path / "f.txt").write_text("y")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
    return tmp_path


def _make_push_repo(tmp_path: Path) -> Path:
    """Create a git repo on main with a remote, ready to push."""
    remote_path = tmp_path / "remote"
    remote_path.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote_path)], capture_output=True)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo_path)], capture_output=True)
    (repo_path / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(repo_path), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "init"], capture_output=True)
    subprocess.run(["git", "-C", str(repo_path), "remote", "add", "origin", str(remote_path)], capture_output=True)
    return repo_path


# ── DESTRUCTIVE: blocked for all roles ───────────────────────────────────────


@pytest.mark.timeout(10, method="thread")
class TestDestructive:
    """Destructive operations are blocked for every role."""

    @pytest.mark.parametrize("role", [None, "worker", "system", "orchestrator", "integrator"])
    def test_restore_blocked(self, role: str | None) -> None:
        result = _run_wrapper(["restore", "file.txt"], role=role)
        assert result.returncode != 0
        assert "destructive" in result.stderr.lower()

    @pytest.mark.parametrize("role", [None, "worker", "system", "orchestrator", "integrator"])
    def test_clean_blocked(self, role: str | None) -> None:
        result = _run_wrapper(["clean", "-fd"], role=role)
        assert result.returncode != 0
        assert "destructive" in result.stderr.lower()

    @pytest.mark.parametrize("role", [None, "worker", "system", "orchestrator", "integrator"])
    def test_switch_blocked(self, role: str | None) -> None:
        result = _run_wrapper(["switch", "main"], role=role)
        assert result.returncode != 0
        assert "destructive" in result.stderr.lower()

    @pytest.mark.parametrize("role", [None, "worker", "system", "orchestrator", "integrator"])
    def test_revert_without_confirmed_blocked(self, role: str | None) -> None:
        result = _run_wrapper(["revert", "abc123"], role=role)
        assert result.returncode != 0
        assert "inspection required" in result.stderr.lower()

    @pytest.mark.parametrize("role", ["worker", "system", "orchestrator", "integrator"])
    def test_reset_hard_blocked(self, role: str | None) -> None:
        result = _run_wrapper(["reset", "--hard"], role=role)
        assert result.returncode != 0

    def test_reset_bare_blocked(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        result = _run_wrapper(["reset"], cwd=str(tmp_path))
        assert result.returncode != 0

    def test_reset_pathspec_allowed(self, tmp_path: Path) -> None:
        repo = _make_branch_repo(tmp_path)
        result = _run_wrapper(["reset", "HEAD", "f.txt"], cwd=str(repo))
        assert result.returncode == 0

    def test_reset_separator_pathspec_allowed(self, tmp_path: Path) -> None:
        repo = _make_branch_repo(tmp_path)
        result = _run_wrapper(["reset", "--", "f.txt"], cwd=str(repo))
        assert result.returncode == 0


# ── PROTECTED: stash (integrator only) ───────────────────────────────────────


@pytest.mark.timeout(10, method="thread")
class TestProtectedStash:
    """Stash is a protected operation — integrator only."""

    @pytest.mark.parametrize("role", [None, "worker", "system", "orchestrator"])
    def test_non_integrator_blocked(self, role: str | None) -> None:
        result = _run_wrapper(["stash"], role=role)
        assert result.returncode != 0
        assert "protected" in result.stderr.lower()

    def test_integrator_allowed(self) -> None:
        result = _run_wrapper(["stash"], role="integrator")
        assert "protected" not in result.stderr.lower()


# ── PROTECTED: checkout ──────────────────────────────────────────────────────


@pytest.mark.timeout(10, method="thread")
class TestProtectedCheckout:
    """Checkout: bare blocked for all, file-scoped allowed for integrator+system."""

    @pytest.mark.parametrize("role", [None, "worker", "system", "orchestrator", "integrator"])
    def test_bare_checkout_blocked_for_all(self, role: str | None) -> None:
        result = _run_wrapper(["checkout", "main"], role=role)
        assert result.returncode != 0
        assert "protected" in result.stderr.lower()

    def test_file_scoped_blocked_for_worker(self) -> None:
        result = _run_wrapper(["checkout", "origin/main", "--", "file.txt"])
        assert result.returncode != 0
        assert "protected" in result.stderr.lower()

    def test_file_scoped_blocked_for_orchestrator(self) -> None:
        result = _run_wrapper(["checkout", "origin/main", "--", "file.txt"], role="orchestrator")
        assert result.returncode != 0
        assert "protected" in result.stderr.lower()

    def test_file_scoped_allowed_for_integrator(self) -> None:
        result = _run_wrapper(["checkout", "HEAD", "--", "f.txt"], role="integrator")
        assert "protected" not in result.stderr.lower()

    def test_file_scoped_allowed_for_system(self) -> None:
        result = _run_wrapper(["checkout", "HEAD", "--", "f.txt"], role="system")
        assert "protected" not in result.stderr.lower()


# ── PROTECTED: commit on main (integrator + system) ─────────────────────────


@pytest.mark.timeout(10, method="thread")
class TestProtectedCommitOnMain:
    """Commit on main: integrator and system allowed, all others blocked."""

    def test_worker_blocked(self, tmp_path: Path) -> None:
        repo = _make_main_repo(tmp_path)
        result = _run_wrapper(["commit", "-m", "test"], cwd=str(repo))
        assert result.returncode != 0
        assert "protected" in result.stderr.lower()

    def test_orchestrator_blocked(self, tmp_path: Path) -> None:
        repo = _make_main_repo(tmp_path)
        result = _run_wrapper(["commit", "-m", "test"], role="orchestrator", cwd=str(repo))
        assert result.returncode != 0

    def test_system_allowed(self, tmp_path: Path) -> None:
        repo = _make_main_repo(tmp_path)
        result = _run_wrapper(["commit", "-m", "test"], role="system", cwd=str(repo))
        assert result.returncode == 0

    def test_integrator_allowed(self, tmp_path: Path) -> None:
        repo = _make_main_repo(tmp_path)
        result = _run_wrapper(["commit", "-m", "test"], role="integrator", cwd=str(repo))
        assert result.returncode == 0

    def test_error_message_does_not_contain_bypass(self, tmp_path: Path) -> None:
        """Error message must not teach agents to set TELECLAUDE_SYSTEM_ROLE."""
        repo = _make_main_repo(tmp_path)
        result = _run_wrapper(["commit", "-m", "test"], cwd=str(repo))
        assert "TELECLAUDE_SYSTEM_ROLE=system" not in result.stderr


# ── PROTECTED: push from main (integrator + system) ─────────────────────────


@pytest.mark.timeout(10, method="thread")
class TestProtectedPushFromMain:
    """Push from main: integrator and system allowed, all others blocked."""

    def test_worker_blocked(self, tmp_path: Path) -> None:
        repo = _make_push_repo(tmp_path)
        result = _run_wrapper(["push", "origin", "main"], cwd=str(repo))
        assert result.returncode != 0
        assert "protected" in result.stderr.lower()

    def test_orchestrator_blocked(self, tmp_path: Path) -> None:
        repo = _make_push_repo(tmp_path)
        result = _run_wrapper(["push", "origin", "main"], role="orchestrator", cwd=str(repo))
        assert result.returncode != 0
        assert "protected" in result.stderr.lower()

    def test_system_allowed(self, tmp_path: Path) -> None:
        repo = _make_push_repo(tmp_path)
        result = _run_wrapper(["push", "origin", "main"], role="system", cwd=str(repo))
        assert result.returncode == 0

    def test_integrator_allowed(self, tmp_path: Path) -> None:
        repo = _make_push_repo(tmp_path)
        result = _run_wrapper(["push", "origin", "main"], role="integrator", cwd=str(repo))
        assert result.returncode == 0


# ── ORCHESTRATOR RESTRICTION: no commit anywhere ─────────────────────────────


@pytest.mark.timeout(10, method="thread")
class TestOrchestratorRestriction:
    """Orchestrators cannot commit on any branch."""

    def test_orchestrator_blocked_on_branch(self, tmp_path: Path) -> None:
        repo = _make_branch_repo(tmp_path)
        result = _run_wrapper(["commit", "-m", "test"], role="orchestrator", cwd=str(repo))
        assert result.returncode != 0
        assert "orchestrator" in result.stderr.lower()

    def test_orchestrator_blocked_on_main(self, tmp_path: Path) -> None:
        repo = _make_main_repo(tmp_path)
        result = _run_wrapper(["commit", "-m", "test"], role="orchestrator", cwd=str(repo))
        assert result.returncode != 0

    def test_worker_allowed_on_branch(self, tmp_path: Path) -> None:
        repo = _make_branch_repo(tmp_path)
        result = _run_wrapper(["commit", "-m", "test"], role="worker", cwd=str(repo))
        assert result.returncode == 0

    def test_system_allowed_on_branch(self, tmp_path: Path) -> None:
        repo = _make_branch_repo(tmp_path)
        result = _run_wrapper(["commit", "-m", "test"], role="system", cwd=str(repo))
        assert result.returncode == 0


# ── INVALID ROLES: fail-closed to worker ─────────────────────────────────────


class TestInvalidRolePermissions:
    """Typoed or invalid roles fall back to worker (fail-closed)."""

    @pytest.mark.parametrize("invalid_role", ["admin", "Integrator", "", " "])
    def test_invalid_role_blocked_from_stash(self, invalid_role: str) -> None:
        result = _run_wrapper(["stash"], role=invalid_role)
        assert result.returncode != 0
        assert "protected" in result.stderr.lower()
