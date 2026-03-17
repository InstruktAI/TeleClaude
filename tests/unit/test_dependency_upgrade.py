"""Tests for the dependency upgrade job.

Behavioral contracts for lockfile parsing, version comparison,
conservative cap generation, command execution, git operations,
validation, and job orchestration.
"""

from __future__ import annotations

import subprocess as subprocess_mod
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from jobs.dependency_upgrade import (
    DependencyUpgradeJob,
    _apply_conservative_caps,
    _find_major_bumps,
    _parse_lockfile_versions,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOCKFILE_TWO_PACKAGES = """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "aiohttp"
version = "3.9.5"

[[package]]
name = "pyyaml"
version = "6.0.2"
"""

LOCKFILE_EMPTY = """\
version = 1
requires-python = ">=3.12"
"""

LOCKFILE_MISSING_FIELDS = """\
version = 1

[[package]]
name = "good"
version = "1.0.0"

[[package]]
name = "no-version"

[[package]]
version = "2.0.0"
"""

LOCKFILE_MAJOR_BUMP = """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "aiohttp"
version = "4.0.0"

[[package]]
name = "pyyaml"
version = "6.0.2"
"""

LOCKFILE_MINOR_BUMP = """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "aiohttp"
version = "3.10.0"

[[package]]
name = "pyyaml"
version = "6.0.2"
"""

PYPROJECT_MINIMAL = """\
[project]
name = "test"
version = "0.1.0"
dependencies = ["aiohttp>=3.9.0"]
"""


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------


def _make_job(
    tmp_path: Path,
    *,
    lock_content: str = LOCKFILE_TWO_PACKAGES,
    pyproject_content: str = PYPROJECT_MINIMAL,
) -> DependencyUpgradeJob:
    """Create a job with paths pointing to tmp_path files."""
    job = DependencyUpgradeJob()
    lock = tmp_path / "uv.lock"
    lock.write_text(lock_content)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(pyproject_content)
    job._lockfile_path = lock
    job._pyproject_path = pyproject
    return job


def _make_command_router(
    lock_path: Path,
    *,
    lock_writes: Sequence[str] | None = None,
    lock_results: Sequence[tuple[bool, str]] | None = None,
    sync_results: Sequence[tuple[bool, str]] | None = None,
) -> Callable[..., tuple[bool, str]]:
    """Build a mock _run_command that routes by command signature.

    Routes uv lock/sync calls through sequenced results.
    All other commands return (True, "ok").
    """
    lock_call_idx = 0
    sync_call_idx = 0

    def router(cmd: list[str], **_kwargs: Any) -> tuple[bool, str]:
        nonlocal lock_call_idx, sync_call_idx
        if cmd[0] == "uv" and "lock" in cmd:
            idx = lock_call_idx
            lock_call_idx += 1
            if lock_writes and idx < len(lock_writes):
                lock_path.write_text(lock_writes[idx])
            if lock_results and idx < len(lock_results):
                return lock_results[idx]
            return True, "ok"
        if cmd[0] == "uv" and "sync" in cmd:
            idx = sync_call_idx
            sync_call_idx += 1
            if sync_results and idx < len(sync_results):
                return sync_results[idx]
            return True, "ok"
        return True, "ok"

    return router


# ---------------------------------------------------------------------------
# Lockfile parsing
# ---------------------------------------------------------------------------


class TestParseLockfileVersions:
    """_parse_lockfile_versions extracts {name: version} from TOML lockfile."""

    def test_returns_dict_from_valid_lockfile(self, tmp_path: Path) -> None:
        lock = tmp_path / "uv.lock"
        lock.write_text(LOCKFILE_TWO_PACKAGES)
        result = _parse_lockfile_versions(lock)
        assert result == {"aiohttp": "3.9.5", "pyyaml": "6.0.2"}

    def test_accepts_bytes_input(self) -> None:
        result = _parse_lockfile_versions(LOCKFILE_TWO_PACKAGES.encode())
        assert result == {"aiohttp": "3.9.5", "pyyaml": "6.0.2"}

    def test_returns_empty_dict_when_no_packages(self, tmp_path: Path) -> None:
        lock = tmp_path / "uv.lock"
        lock.write_text(LOCKFILE_EMPTY)
        assert _parse_lockfile_versions(lock) == {}

    def test_skips_packages_missing_name_or_version(self, tmp_path: Path) -> None:
        lock = tmp_path / "uv.lock"
        lock.write_text(LOCKFILE_MISSING_FIELDS)
        result = _parse_lockfile_versions(lock)
        assert result == {"good": "1.0.0"}


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------


class TestFindMajorBumps:
    """_find_major_bumps detects major version changes between old and new."""

    def test_detects_major_bump(self) -> None:
        old = {"aiohttp": "3.9.5"}
        new = {"aiohttp": "4.0.0"}
        result = _find_major_bumps(old, new)
        assert result == {"aiohttp": ("3.9.5", "4.0.0")}

    @pytest.mark.parametrize(
        ("old_ver", "new_ver"),
        [("3.0.0", "3.5.0"), ("3.9.0", "3.9.3")],
        ids=["minor", "patch"],
    )
    def test_ignores_non_major_bumps(self, old_ver: str, new_ver: str) -> None:
        old = {"aiohttp": old_ver}
        new = {"aiohttp": new_ver}
        assert _find_major_bumps(old, new) == {}

    def test_ignores_new_packages(self) -> None:
        old: dict[str, str] = {}
        new = {"newpkg": "2.0.0"}
        assert _find_major_bumps(old, new) == {}

    def test_skips_unparseable_versions(self) -> None:
        old = {"bad": "not-a-version"}
        new = {"bad": "also-bad"}
        assert _find_major_bumps(old, new) == {}


# ---------------------------------------------------------------------------
# Conservative cap generation
# ---------------------------------------------------------------------------


class TestApplyConservativeCaps:
    """_apply_conservative_caps appends override-dependencies to pyproject.toml."""

    def test_appends_uv_override_section(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_MINIMAL)
        bumps = {"aiohttp": ("3.9.5", "4.0.0")}
        original = _apply_conservative_caps(pyproject, bumps)
        content = pyproject.read_text()
        assert "[tool.uv]" in content
        assert "override-dependencies" in content
        assert '"aiohttp<4"' in content
        assert original == PYPROJECT_MINIMAL

    def test_multiple_bumps_sorted(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_MINIMAL)
        bumps = {"pyyaml": ("6.0.2", "7.0.0"), "aiohttp": ("3.9.5", "4.0.0")}
        _apply_conservative_caps(pyproject, bumps)
        content = pyproject.read_text()
        aiohttp_pos = content.index('"aiohttp<4"')
        pyyaml_pos = content.index('"pyyaml<7"')
        assert aiohttp_pos < pyyaml_pos


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------


class TestRunCommand:
    """_run_command wraps subprocess.run with consistent interface."""

    def test_returns_success_and_combined_output(self) -> None:
        job = DependencyUpgradeJob()
        mock_result = MagicMock(returncode=0, stdout="out\n", stderr="err\n")
        with patch("jobs.dependency_upgrade.subprocess.run", return_value=mock_result) as mock_run:
            ok, output = job._run_command(["echo", "test"])
        assert ok is True
        assert output == "out\nerr\n"
        mock_run.assert_called_once()

    def test_returns_failure_on_nonzero_exit(self) -> None:
        job = DependencyUpgradeJob()
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        with patch("jobs.dependency_upgrade.subprocess.run", return_value=mock_result):
            ok, _output = job._run_command(["false"])
        assert ok is False

    def test_returns_failure_on_timeout(self) -> None:
        job = DependencyUpgradeJob()
        with patch(
            "jobs.dependency_upgrade.subprocess.run",
            side_effect=subprocess_mod.TimeoutExpired(cmd=["slow"], timeout=600),
        ):
            ok, _output = job._run_command(["slow"])
        assert ok is False

    def test_returns_failure_on_unexpected_exception(self) -> None:
        job = DependencyUpgradeJob()
        with patch(
            "jobs.dependency_upgrade.subprocess.run",
            side_effect=OSError("no such file"),
        ):
            ok, _output = job._run_command(["nonexistent"])
        assert ok is False

    def test_env_merges_with_os_environ(self) -> None:
        job = DependencyUpgradeJob()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        custom_env = {"CUSTOM": "1"}
        with patch("jobs.dependency_upgrade.subprocess.run", return_value=mock_result) as mock_run:
            job._run_command(["echo"], env=custom_env)
        _, kwargs = mock_run.call_args
        passed_env = kwargs["env"]
        assert passed_env["CUSTOM"] == "1"
        assert "HOME" in passed_env or "PATH" in passed_env

    def test_env_none_passes_none_to_subprocess(self) -> None:
        job = DependencyUpgradeJob()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("jobs.dependency_upgrade.subprocess.run", return_value=mock_result) as mock_run:
            job._run_command(["echo"])
        _, kwargs = mock_run.call_args
        assert kwargs["env"] is None


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------


class TestGitCommitAndPush:
    """_git_commit_and_push stages uv.lock, commits with mode, pushes."""

    def _make_capture(
        self, *, diff_output: str = ""
    ) -> tuple[  # guard: loose-dict - captures arbitrary **kw from _run_command
        Callable[..., tuple[bool, str]], list[tuple[list[str], dict[str, Any]]]
    ]:
        """Return a mock _run_command that captures all calls."""
        # guard: loose-dict - captures arbitrary **kw from _run_command
        captured: list[tuple[list[str], dict[str, Any]]] = []

        def capture(cmd: list[str], **kw: dict[str, str] | None) -> tuple[bool, str]:
            captured.append((cmd, kw))
            if cmd[:2] == ["git", "diff"]:
                return True, diff_output
            return True, "ok"

        return capture, captured

    def test_stages_only_uv_lock(self) -> None:
        job = DependencyUpgradeJob()
        capture, captured = self._make_capture()
        with patch.object(job, "_run_command", side_effect=capture):
            job._git_commit_and_push("aggressive")
        assert captured[0][0] == ["git", "add", "uv.lock"]

    @pytest.mark.parametrize("mode", ["aggressive", "conservative"])
    def test_commit_message_contains_mode(self, mode: str) -> None:
        job = DependencyUpgradeJob()
        capture, captured = self._make_capture()
        with patch.object(job, "_run_command", side_effect=capture):
            job._git_commit_and_push(mode)
        commit_cmds = [c for c, _kw in captured if c[:2] == ["git", "commit"]]
        assert len(commit_cmds) == 1
        msg = commit_cmds[0][commit_cmds[0].index("-m") + 1]
        assert mode in msg

    def test_passes_system_role_to_git_commands(self) -> None:
        job = DependencyUpgradeJob()
        capture, captured = self._make_capture()
        with patch.object(job, "_run_command", side_effect=capture):
            job._git_commit_and_push("aggressive")
        envs_with_vars = [kw["env"] for _cmd, kw in captured if kw.get("env") is not None]
        assert len(envs_with_vars) >= 3
        for env in envs_with_vars:
            assert env["TELECLAUDE_SYSTEM_ROLE"] == "system"

    def test_returns_failure_when_git_add_fails(self) -> None:
        job = DependencyUpgradeJob()
        captured: list[list[str]] = []

        def capture(cmd: list[str], **_kw: Any) -> tuple[bool, str]:
            captured.append(cmd)
            if cmd[:2] == ["git", "add"]:
                return False, "add failed"
            return True, "ok"

        with patch.object(job, "_run_command", side_effect=capture):
            ok, _msg = job._git_commit_and_push("aggressive")

        assert ok is False
        commit_calls = [c for c in captured if c[:2] == ["git", "commit"]]
        assert commit_calls == []

    def test_commit_uses_no_verify(self) -> None:
        job = DependencyUpgradeJob()
        capture, captured = self._make_capture()
        with patch.object(job, "_run_command", side_effect=capture):
            job._git_commit_and_push("aggressive")
        commit_cmds = [c for c, _kw in captured if c[:2] == ["git", "commit"]]
        assert len(commit_cmds) == 1
        assert "--no-verify" in commit_cmds[0]

    def test_stages_lint_modified_files(self) -> None:
        job = DependencyUpgradeJob()
        capture, captured = self._make_capture(diff_output="src/foo.py\nsrc/bar.py\n")
        with patch.object(job, "_run_command", side_effect=capture):
            job._git_commit_and_push("aggressive")
        add_cmds = [c for c, _kw in captured if c[:2] == ["git", "add"]]
        staged_files = [c[2] for c in add_cmds]
        assert "uv.lock" in staged_files
        assert "src/foo.py" in staged_files
        assert "src/bar.py" in staged_files


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestRunValidation:
    """_run_validation runs lint then tests, short-circuits on failure."""

    def test_passes_when_both_succeed(self) -> None:
        job = DependencyUpgradeJob()
        with patch.object(job, "_run_command", return_value=(True, "ok")):
            ok, _msg = job._run_validation()
        assert ok is True

    def test_fails_on_lint_failure(self) -> None:
        job = DependencyUpgradeJob()
        call_count = 0

        def mock_cmd(cmd: list[str], **_kw: Any) -> tuple[bool, str]:
            nonlocal call_count
            call_count += 1
            if "lint" in cmd[-1]:
                return False, "lint error"
            return True, "ok"

        with patch.object(job, "_run_command", side_effect=mock_cmd):
            ok, _msg = job._run_validation()

        assert ok is False
        assert call_count == 1

    def test_fails_on_test_failure(self) -> None:
        job = DependencyUpgradeJob()

        def mock_cmd(cmd: list[str], **_kw: Any) -> tuple[bool, str]:
            if "test" in cmd[-1]:
                return False, "test error"
            return True, "ok"

        with patch.object(job, "_run_command", side_effect=mock_cmd):
            ok, _msg = job._run_validation()

        assert ok is False


# ---------------------------------------------------------------------------
# Job orchestration
# ---------------------------------------------------------------------------


class TestJobOrchestration:
    """End-to-end orchestration via mocked subprocess calls."""

    def test_lockfile_missing_returns_failure(self, tmp_path: Path) -> None:
        job = DependencyUpgradeJob()
        job._lockfile_path = tmp_path / "nonexistent.lock"
        job._pyproject_path = tmp_path / "pyproject.toml"
        result = job.run()
        assert result.success is False

    def test_aggressive_success_commits(self, tmp_path: Path) -> None:
        job = _make_job(tmp_path)
        router = _make_command_router(job._lockfile_path, lock_writes=[LOCKFILE_MINOR_BUMP])

        with (
            patch.object(job, "_run_command", side_effect=router),
            patch.object(job, "_run_validation", return_value=(True, "all green")),
            patch.object(job, "_git_commit_and_push", return_value=(True, "pushed")),
        ):
            result = job.run()

        assert result.success is True

    def test_no_changes_skips_commit(self, tmp_path: Path) -> None:
        job = _make_job(tmp_path)
        router = _make_command_router(job._lockfile_path)

        with patch.object(job, "_run_command", side_effect=router):
            result = job.run()

        assert result.success is True

    def test_uv_lock_failure_restores_lockfile(self, tmp_path: Path) -> None:
        job = _make_job(tmp_path)
        original = job._lockfile_path.read_text()
        router = _make_command_router(
            job._lockfile_path,
            lock_results=[(False, "lock failed")],
        )

        with patch.object(job, "_run_command", side_effect=router):
            result = job.run()

        assert result.success is False
        assert job._lockfile_path.read_text() == original

    def test_aggressive_sync_failure_restores_lockfile(self, tmp_path: Path) -> None:
        job = _make_job(tmp_path)
        original = job._lockfile_path.read_text()
        router = _make_command_router(
            job._lockfile_path,
            lock_writes=[LOCKFILE_MINOR_BUMP],
            sync_results=[(False, "sync failed")],
        )

        with patch.object(job, "_run_command", side_effect=router):
            result = job.run()

        assert result.success is False
        assert job._lockfile_path.read_text() == original

    def test_aggressive_push_failure_restores_lockfile(self, tmp_path: Path) -> None:
        job = _make_job(tmp_path)
        original = job._lockfile_path.read_text()
        router = _make_command_router(job._lockfile_path, lock_writes=[LOCKFILE_MINOR_BUMP])

        with (
            patch.object(job, "_run_command", side_effect=router),
            patch.object(job, "_run_validation", return_value=(True, "ok")),
            patch.object(job, "_git_commit_and_push", return_value=(False, "push failed")),
        ):
            result = job.run()

        assert result.success is False
        assert job._lockfile_path.read_text() == original

    def test_aggressive_fails_no_major_bumps_restores(self, tmp_path: Path) -> None:
        job = _make_job(tmp_path)
        original = job._lockfile_path.read_text()
        router = _make_command_router(job._lockfile_path, lock_writes=[LOCKFILE_MINOR_BUMP])

        with (
            patch.object(job, "_run_command", side_effect=router),
            patch.object(job, "_run_validation", return_value=(False, "tests failed")),
        ):
            result = job.run()

        assert result.success is False
        assert job._lockfile_path.read_text() == original

    def test_aggressive_fails_conservative_succeeds(self, tmp_path: Path) -> None:
        job = _make_job(tmp_path)
        router = _make_command_router(
            job._lockfile_path,
            lock_writes=[LOCKFILE_MAJOR_BUMP, LOCKFILE_MINOR_BUMP],
        )
        validation_call = 0

        def mock_validation() -> tuple[bool, str]:
            nonlocal validation_call
            validation_call += 1
            return (False, "tests failed") if validation_call == 1 else (True, "all green")

        with (
            patch.object(job, "_run_command", side_effect=router),
            patch.object(job, "_run_validation", side_effect=mock_validation),
            patch.object(job, "_git_commit_and_push", return_value=(True, "pushed")),
        ):
            result = job.run()

        assert result.success is True

    def test_both_tiers_fail(self, tmp_path: Path) -> None:
        job = _make_job(tmp_path)
        original_lock = job._lockfile_path.read_text()
        original_pyproject = job._pyproject_path.read_text()
        router = _make_command_router(
            job._lockfile_path,
            lock_writes=[LOCKFILE_MAJOR_BUMP, LOCKFILE_MINOR_BUMP],
        )

        with (
            patch.object(job, "_run_command", side_effect=router),
            patch.object(job, "_run_validation", return_value=(False, "tests failed")),
        ):
            result = job.run()

        assert result.success is False
        assert job._lockfile_path.read_text() == original_lock
        assert job._pyproject_path.read_text() == original_pyproject

    def test_conservative_sync_failure_restores(self, tmp_path: Path) -> None:
        job = _make_job(tmp_path)
        original_lock = job._lockfile_path.read_text()
        original_pyproject = job._pyproject_path.read_text()
        router = _make_command_router(
            job._lockfile_path,
            lock_writes=[LOCKFILE_MAJOR_BUMP, LOCKFILE_MINOR_BUMP],
            sync_results=[(True, "ok"), (False, "sync failed")],
        )

        with (
            patch.object(job, "_run_command", side_effect=router),
            patch.object(job, "_run_validation", return_value=(False, "tests failed")),
        ):
            result = job.run()

        assert result.success is False
        assert job._lockfile_path.read_text() == original_lock
        assert job._pyproject_path.read_text() == original_pyproject

    def test_conservative_push_failure_restores(self, tmp_path: Path) -> None:
        job = _make_job(tmp_path)
        original_lock = job._lockfile_path.read_text()
        original_pyproject = job._pyproject_path.read_text()
        router = _make_command_router(
            job._lockfile_path,
            lock_writes=[LOCKFILE_MAJOR_BUMP, LOCKFILE_MINOR_BUMP],
        )
        validation_call = 0

        def mock_validation() -> tuple[bool, str]:
            nonlocal validation_call
            validation_call += 1
            return (False, "tests failed") if validation_call == 1 else (True, "all green")

        with (
            patch.object(job, "_run_command", side_effect=router),
            patch.object(job, "_run_validation", side_effect=mock_validation),
            patch.object(job, "_git_commit_and_push", return_value=(False, "push failed")),
        ):
            result = job.run()

        assert result.success is False
        assert job._lockfile_path.read_text() == original_lock
        assert job._pyproject_path.read_text() == original_pyproject

    def test_pyproject_restored_on_conservative_failure(self, tmp_path: Path) -> None:
        """Verify the finally block restores pyproject even when conservative fails.

        Unlike conservative success (where L243 restores pyproject before the
        finally block), this failure path relies solely on the finally block at
        L255-257 for pyproject restoration.
        """
        job = _make_job(tmp_path)
        original_pyproject = job._pyproject_path.read_text()
        router = _make_command_router(
            job._lockfile_path,
            lock_writes=[LOCKFILE_MAJOR_BUMP, LOCKFILE_MINOR_BUMP],
        )

        with (
            patch.object(job, "_run_command", side_effect=router),
            patch.object(job, "_run_validation", return_value=(False, "tests failed")),
        ):
            result = job.run()

        assert result.success is False
        # Caps were applied by _apply_conservative_caps before the try block.
        # Only the finally block restores pyproject on this failure path.
        assert job._pyproject_path.read_text() == original_pyproject
