# guard: no-companion
"""Behavioral tests for the git wrapper three-tier permission model.

Tests import the wrapper as a Python module and call main() directly,
mocking gitpython for actual git execution. No subprocess.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

WRAPPER_PATH = Path(__file__).resolve().parents[3] / "teleclaude" / "install" / "wrappers" / "git"


def _load_wrapper() -> ModuleType:
    """Import the git wrapper as a module.

    The wrapper has no .py extension (it uses a uv run shebang), so we must
    provide a loader explicitly — spec_from_file_location returns None for
    extensionless files without one.
    """
    loader = importlib.machinery.SourceFileLoader("git_wrapper", str(WRAPPER_PATH))
    spec = importlib.util.spec_from_file_location("git_wrapper", WRAPPER_PATH, loader=loader)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_wrapper = _load_wrapper()


def _run(
    args: list[str],
    role: str | None = None,
    cwd: str | None = None,
    *,
    human_role: str | None = None,
    branch: str = "feature",
    no_identity_file: bool = False,
) -> tuple[int, str]:
    """Run the wrapper's main() with mocked identity and git, return (exit_code, stderr)."""
    session_tmpdir = Path(tempfile.mkdtemp())
    if not no_identity_file:
        identity: dict[str, str] = {"session_id": "test-session"}
        if role is not None:
            identity["system_role"] = role
        if human_role is not None:
            identity["human_role"] = human_role
        (session_tmpdir / "teleclaude_identity.json").write_text(json.dumps(identity))

    mock_git_cmd = MagicMock()
    mock_git_cmd.execute.return_value = ""

    captured_stderr: list[str] = []
    exit_code = 0

    def fake_print(*a: object, **kw: object) -> None:
        import sys as _sys

        if kw.get("file") is _sys.stderr:
            captured_stderr.append(" ".join(str(x) for x in a))
        else:
            # stdout output (e.g. git command output) — discard in tests
            pass

    env_overrides = {"TMPDIR": str(session_tmpdir), "TELECLAUDE_SYSTEM_ROLE": ""}

    mock_gp = MagicMock()
    mock_gp.cmd.Git.return_value = mock_git_cmd
    mock_gp.exc.GitCommandError = Exception

    with (
        patch.dict(os.environ, env_overrides),
        patch.object(_wrapper, "_get_gitpython", return_value=mock_gp),
        patch.object(_wrapper, "get_current_branch", return_value=branch),
        patch("sys.argv", ["git"] + args),
        patch("builtins.print", side_effect=fake_print),
    ):
        if cwd:
            with patch.object(Path, "cwd", return_value=Path(cwd).resolve()):
                try:
                    _wrapper.main()
                except SystemExit as exc:
                    exit_code = exc.code if isinstance(exc.code, int) else 1
        else:
            try:
                _wrapper.main()
            except SystemExit as exc:
                exit_code = exc.code if isinstance(exc.code, int) else 1

    return exit_code, "\n".join(captured_stderr)


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
        code, _ = _run(["commit", "-m", "human commit"], human_role="admin", branch="main")
        assert code == 0

    def test_human_blocked_outside_cwd(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        code, stderr = _run(["-C", str(other), "status"], human_role="admin", cwd=str(repo))
        assert code != 0
        assert "outside" in stderr.lower()

    def test_human_allowed_in_subdirectory(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        code, _ = _run(["-C", str(sub), "status"], human_role="admin", cwd=str(tmp_path))
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
