"""Behavioral tests for the git wrapper permission model.

Tests that the wrapper blocks/allows git subcommands based on TELECLAUDE_SYSTEM_ROLE.
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


class TestStashPermissions:
    def test_worker_blocked(self) -> None:
        result = _run_wrapper(["stash"])
        assert result.returncode != 0
        assert "prohibited" in result.stderr

    def test_default_blocked(self) -> None:
        result = _run_wrapper(["stash"], role=None)
        assert result.returncode != 0

    def test_integrator_allowed(self, tmp_path: Path) -> None:
        # Init a real repo so stash has something to work with
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / "f.txt").write_text("x")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True)
        # stash with nothing to stash returns 1, but the point is the wrapper doesn't block it
        result = _run_wrapper(["stash"], role="integrator", cwd=str(tmp_path))
        # Wrapper should NOT emit "prohibited" — it passes through to real git
        assert "prohibited" not in result.stderr

    def test_system_blocked(self) -> None:
        result = _run_wrapper(["stash"], role="system")
        assert result.returncode != 0
        assert "prohibited" in result.stderr


class TestCheckoutPermissions:
    def test_bare_checkout_blocked_for_all(self) -> None:
        for role in [None, "worker", "integrator", "system", "orchestrator"]:
            result = _run_wrapper(["checkout", "main"], role=role)
            assert result.returncode != 0, f"bare checkout should be blocked for role={role}"
            assert "prohibited" in result.stderr

    def test_file_scoped_checkout_blocked_for_worker(self) -> None:
        result = _run_wrapper(["checkout", "origin/main", "--", "file.txt"])
        assert result.returncode != 0
        assert "prohibited" in result.stderr

    def test_file_scoped_checkout_blocked_for_orchestrator(self) -> None:
        result = _run_wrapper(["checkout", "origin/main", "--", "file.txt"], role="orchestrator")
        assert result.returncode != 0
        assert "prohibited" in result.stderr

    def test_file_scoped_checkout_allowed_for_integrator(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / "f.txt").write_text("x")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True)
        result = _run_wrapper(["checkout", "HEAD", "--", "f.txt"], role="integrator", cwd=str(tmp_path))
        assert "prohibited" not in result.stderr

    def test_file_scoped_checkout_allowed_for_system(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / "f.txt").write_text("x")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True)
        result = _run_wrapper(["checkout", "HEAD", "--", "f.txt"], role="system", cwd=str(tmp_path))
        assert "prohibited" not in result.stderr


class TestCommitOnMainPermissions:
    """Commit-on-main requires the branch to actually be 'main'."""

    def _make_main_repo(self, tmp_path: Path) -> Path:
        subprocess.run(["git", "init", "-b", "main", str(tmp_path)], capture_output=True)
        (tmp_path / "f.txt").write_text("x")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True)
        (tmp_path / "f.txt").write_text("y")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
        return tmp_path

    def test_worker_blocked(self, tmp_path: Path) -> None:
        repo = self._make_main_repo(tmp_path)
        result = _run_wrapper(["commit", "-m", "test"], cwd=str(repo))
        assert result.returncode != 0
        assert "blocked" in result.stderr.lower()

    def test_system_allowed(self, tmp_path: Path) -> None:
        repo = self._make_main_repo(tmp_path)
        result = _run_wrapper(["commit", "-m", "test"], role="system", cwd=str(repo))
        assert result.returncode == 0

    def test_integrator_blocked(self, tmp_path: Path) -> None:
        repo = self._make_main_repo(tmp_path)
        result = _run_wrapper(["commit", "-m", "test"], role="integrator", cwd=str(repo))
        assert result.returncode != 0

    def test_orchestrator_blocked(self, tmp_path: Path) -> None:
        repo = self._make_main_repo(tmp_path)
        result = _run_wrapper(["commit", "-m", "test"], role="orchestrator", cwd=str(repo))
        assert result.returncode != 0


class TestPushFromMainPermissions:
    """Push-from-main requires the branch to actually be 'main' and the 'system' role."""

    def _make_main_repo(self, tmp_path: Path) -> Path:
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

    def test_worker_blocked(self, tmp_path: Path) -> None:
        repo = self._make_main_repo(tmp_path)
        result = _run_wrapper(["push", "origin", "main"], cwd=str(repo))
        assert result.returncode != 0
        assert "blocked" in result.stderr.lower()

    def test_system_allowed(self, tmp_path: Path) -> None:
        repo = self._make_main_repo(tmp_path)
        result = _run_wrapper(["push", "origin", "main"], role="system", cwd=str(repo))
        assert result.returncode == 0
        assert "Only the system role may push" not in result.stderr

    def test_integrator_blocked(self, tmp_path: Path) -> None:
        repo = self._make_main_repo(tmp_path)
        result = _run_wrapper(["push", "origin", "main"], role="integrator", cwd=str(repo))
        assert result.returncode != 0
        assert "blocked" in result.stderr.lower()

    def test_orchestrator_blocked(self, tmp_path: Path) -> None:
        repo = self._make_main_repo(tmp_path)
        result = _run_wrapper(["push", "origin", "main"], role="orchestrator", cwd=str(repo))
        assert result.returncode != 0
        assert "blocked" in result.stderr.lower()


class TestInvalidRolePermissions:
    """Typoed or invalid roles should fall back to worker (fail-closed)."""

    @pytest.mark.parametrize("invalid_role", ["admin", "Integrator", "", " "])
    def test_invalid_role_blocked_from_stash(self, invalid_role: str) -> None:
        result = _run_wrapper(["stash"], role=invalid_role)
        assert result.returncode != 0
        assert "prohibited" in result.stderr


class TestAlwaysBlocked:
    """Commands that no role can bypass."""

    def test_restore_blocked(self) -> None:
        result = _run_wrapper(["restore", "file.txt"], role="system")
        assert result.returncode != 0
        assert "prohibited" in result.stderr

    def test_clean_blocked(self) -> None:
        result = _run_wrapper(["clean", "-fd"], role="integrator")
        assert result.returncode != 0
        assert "prohibited" in result.stderr

    def test_reset_hard_blocked(self) -> None:
        result = _run_wrapper(["reset", "--hard"], role="system")
        assert result.returncode != 0
        assert "prohibited" in result.stderr

    def test_revert_without_confirmed_blocked(self) -> None:
        result = _run_wrapper(["revert", "abc123"], role="system")
        assert result.returncode != 0
        assert "inspection required" in result.stderr.lower()
