"""Tests for the dependency upgrade job.

Behavioral contracts for lockfile parsing, version comparison,
conservative cap generation, and job orchestration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Fixtures
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

PYPROJECT_MINIMAL = """\
[project]
name = "test"
version = "0.1.0"
dependencies = ["aiohttp>=3.9.0"]
"""


# ---------------------------------------------------------------------------
# Lockfile parsing
# ---------------------------------------------------------------------------


class TestParseLockfileVersions:
    """_parse_lockfile_versions extracts {name: version} from TOML lockfile."""

    def test_returns_dict_from_valid_lockfile(self, tmp_path: Path) -> None:
        from jobs.dependency_upgrade import _parse_lockfile_versions

        lock = tmp_path / "uv.lock"
        lock.write_text(LOCKFILE_TWO_PACKAGES)
        result = _parse_lockfile_versions(lock)
        assert result == {"aiohttp": "3.9.5", "pyyaml": "6.0.2"}

    def test_returns_empty_dict_when_no_packages(self, tmp_path: Path) -> None:
        from jobs.dependency_upgrade import _parse_lockfile_versions

        lock = tmp_path / "uv.lock"
        lock.write_text(LOCKFILE_EMPTY)
        assert _parse_lockfile_versions(lock) == {}

    def test_skips_packages_missing_name_or_version(self, tmp_path: Path) -> None:
        from jobs.dependency_upgrade import _parse_lockfile_versions

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
        from jobs.dependency_upgrade import _find_major_bumps

        old = {"aiohttp": "3.9.5"}
        new = {"aiohttp": "4.0.0"}
        result = _find_major_bumps(old, new)
        assert "aiohttp" in result
        assert result["aiohttp"] == ("3.9.5", "4.0.0")

    def test_ignores_minor_bump(self) -> None:
        from jobs.dependency_upgrade import _find_major_bumps

        old = {"aiohttp": "3.0.0"}
        new = {"aiohttp": "3.5.0"}
        assert _find_major_bumps(old, new) == {}

    def test_ignores_patch_bump(self) -> None:
        from jobs.dependency_upgrade import _find_major_bumps

        old = {"aiohttp": "3.9.0"}
        new = {"aiohttp": "3.9.3"}
        assert _find_major_bumps(old, new) == {}

    def test_ignores_new_packages(self) -> None:
        from jobs.dependency_upgrade import _find_major_bumps

        old: dict[str, str] = {}
        new = {"newpkg": "2.0.0"}
        assert _find_major_bumps(old, new) == {}

    def test_skips_unparseable_versions(self) -> None:
        from jobs.dependency_upgrade import _find_major_bumps

        old = {"bad": "not-a-version"}
        new = {"bad": "also-bad"}
        assert _find_major_bumps(old, new) == {}


# ---------------------------------------------------------------------------
# Conservative cap generation
# ---------------------------------------------------------------------------


class TestApplyConservativeCaps:
    """_apply_conservative_caps appends override-dependencies to pyproject.toml."""

    def test_appends_uv_override_section(self, tmp_path: Path) -> None:
        from jobs.dependency_upgrade import _apply_conservative_caps

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_MINIMAL)
        bumps = {"aiohttp": ("3.9.5", "4.0.0")}
        original = _apply_conservative_caps(pyproject, bumps)
        content = pyproject.read_text()
        assert "[tool.uv]" in content
        assert "override-dependencies" in content
        assert '"aiohttp<4"' in content
        assert original == PYPROJECT_MINIMAL

    def test_returns_original_content_for_restoration(self, tmp_path: Path) -> None:
        from jobs.dependency_upgrade import _apply_conservative_caps

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_MINIMAL)
        bumps = {"aiohttp": ("3.9.5", "4.0.0")}
        original = _apply_conservative_caps(pyproject, bumps)
        pyproject.write_text(original)
        assert pyproject.read_text() == PYPROJECT_MINIMAL


# ---------------------------------------------------------------------------
# Job orchestration
# ---------------------------------------------------------------------------


class TestJobOrchestration:
    """End-to-end orchestration via mocked subprocess calls."""

    def test_aggressive_success_commits(self, tmp_path: Path) -> None:
        from jobs.dependency_upgrade import DependencyUpgradeJob

        job = DependencyUpgradeJob()
        lock = tmp_path / "uv.lock"
        lock.write_text(LOCKFILE_TWO_PACKAGES)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_MINIMAL)

        upgraded_lock = LOCKFILE_TWO_PACKAGES.replace("3.9.5", "3.10.0")

        call_count = 0

        def mock_run_command(cmd: list[str], **_kwargs: Any) -> tuple[bool, str]:
            nonlocal call_count
            call_count += 1
            if cmd[0] == "uv" and "lock" in cmd:
                lock.write_text(upgraded_lock)
                return True, "ok"
            if cmd[0] == "uv" and "sync" in cmd:
                return True, "ok"
            return True, "ok"

        with (
            patch.object(job, "_run_command", side_effect=mock_run_command),
            patch.object(job, "_run_validation", return_value=(True, "all green")),
            patch.object(job, "_git_commit_and_push", return_value=(True, "pushed")),
            patch.object(job, "_lockfile_path", lock),
            patch.object(job, "_pyproject_path", pyproject),
        ):
            result = job.run()

        assert result.success is True

    def test_no_changes_skips_commit(self, tmp_path: Path) -> None:
        from jobs.dependency_upgrade import DependencyUpgradeJob

        job = DependencyUpgradeJob()
        lock = tmp_path / "uv.lock"
        lock.write_text(LOCKFILE_TWO_PACKAGES)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_MINIMAL)

        def mock_run_command(cmd: list[str], **_kwargs: Any) -> tuple[bool, str]:
            return True, "ok"

        with (
            patch.object(job, "_run_command", side_effect=mock_run_command),
            patch.object(job, "_lockfile_path", lock),
            patch.object(job, "_pyproject_path", pyproject),
        ):
            result = job.run()

        assert result.success is True
        assert "no changes" in result.message.lower() or "unchanged" in result.message.lower()

    def test_aggressive_fails_conservative_succeeds(self, tmp_path: Path) -> None:
        from jobs.dependency_upgrade import DependencyUpgradeJob

        job = DependencyUpgradeJob()
        lock = tmp_path / "uv.lock"
        lock.write_text(LOCKFILE_TWO_PACKAGES)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_MINIMAL)

        # After aggressive upgrade: aiohttp jumps to 4.0.0
        aggressive_lock = LOCKFILE_TWO_PACKAGES.replace("3.9.5", "4.0.0")
        # After conservative: aiohttp stays at 3.10.0
        conservative_lock = LOCKFILE_TWO_PACKAGES.replace("3.9.5", "3.10.0")

        upgrade_call = 0
        validation_call = 0

        def mock_run_command(cmd: list[str], **_kwargs: Any) -> tuple[bool, str]:
            nonlocal upgrade_call
            if cmd[0] == "uv" and "lock" in cmd:
                upgrade_call += 1
                if upgrade_call == 1:
                    lock.write_text(aggressive_lock)
                else:
                    lock.write_text(conservative_lock)
                return True, "ok"
            return True, "ok"

        def mock_validation() -> tuple[bool, str]:
            nonlocal validation_call
            validation_call += 1
            if validation_call == 1:
                return False, "tests failed"
            return True, "all green"

        with (
            patch.object(job, "_run_command", side_effect=mock_run_command),
            patch.object(job, "_run_validation", side_effect=mock_validation),
            patch.object(job, "_git_commit_and_push", return_value=(True, "pushed")),
            patch.object(job, "_lockfile_path", lock),
            patch.object(job, "_pyproject_path", pyproject),
        ):
            result = job.run()

        assert result.success is True
        assert "conservative" in result.message.lower()

    def test_both_tiers_fail(self, tmp_path: Path) -> None:
        from jobs.dependency_upgrade import DependencyUpgradeJob

        job = DependencyUpgradeJob()
        lock = tmp_path / "uv.lock"
        lock.write_text(LOCKFILE_TWO_PACKAGES)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_MINIMAL)

        aggressive_lock = LOCKFILE_TWO_PACKAGES.replace("3.9.5", "4.0.0")
        conservative_lock = LOCKFILE_TWO_PACKAGES.replace("3.9.5", "3.10.0")
        upgrade_call = 0

        def mock_run_command(cmd: list[str], **_kwargs: Any) -> tuple[bool, str]:
            nonlocal upgrade_call
            if cmd[0] == "uv" and "lock" in cmd:
                upgrade_call += 1
                if upgrade_call == 1:
                    lock.write_text(aggressive_lock)
                else:
                    lock.write_text(conservative_lock)
                return True, "ok"
            return True, "ok"

        with (
            patch.object(job, "_run_command", side_effect=mock_run_command),
            patch.object(job, "_run_validation", return_value=(False, "tests failed")),
            patch.object(job, "_lockfile_path", lock),
            patch.object(job, "_pyproject_path", pyproject),
        ):
            result = job.run()

        assert result.success is False

    def test_aggressive_fails_no_major_bumps_restores(self, tmp_path: Path) -> None:
        from jobs.dependency_upgrade import DependencyUpgradeJob

        job = DependencyUpgradeJob()
        original_content = LOCKFILE_TWO_PACKAGES
        lock = tmp_path / "uv.lock"
        lock.write_text(original_content)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_MINIMAL)

        # Minor bump only — no major bumps to cap
        minor_bump_lock = LOCKFILE_TWO_PACKAGES.replace("3.9.5", "3.10.0")

        def mock_run_command(cmd: list[str], **_kwargs: Any) -> tuple[bool, str]:
            if cmd[0] == "uv" and "lock" in cmd:
                lock.write_text(minor_bump_lock)
                return True, "ok"
            return True, "ok"

        with (
            patch.object(job, "_run_command", side_effect=mock_run_command),
            patch.object(job, "_run_validation", return_value=(False, "tests failed")),
            patch.object(job, "_lockfile_path", lock),
            patch.object(job, "_pyproject_path", pyproject),
        ):
            result = job.run()

        assert result.success is False
        assert lock.read_text() == original_content

    def test_lockfile_restored_on_failure(self, tmp_path: Path) -> None:
        from jobs.dependency_upgrade import DependencyUpgradeJob

        job = DependencyUpgradeJob()
        original_content = LOCKFILE_TWO_PACKAGES
        lock = tmp_path / "uv.lock"
        lock.write_text(original_content)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_MINIMAL)

        def mock_run_command(cmd: list[str], **_kwargs: Any) -> tuple[bool, str]:
            if cmd[0] == "uv" and "lock" in cmd:
                lock.write_text("corrupted")
                return True, "ok"
            return True, "ok"

        with (
            patch.object(job, "_run_command", side_effect=mock_run_command),
            patch.object(job, "_run_validation", return_value=(False, "tests failed")),
            patch.object(job, "_lockfile_path", lock),
            patch.object(job, "_pyproject_path", pyproject),
        ):
            result = job.run()

        assert result.success is False
        assert lock.read_text() == original_content

    def test_pyproject_restored_after_conservative(self, tmp_path: Path) -> None:
        from jobs.dependency_upgrade import DependencyUpgradeJob

        job = DependencyUpgradeJob()
        lock = tmp_path / "uv.lock"
        lock.write_text(LOCKFILE_TWO_PACKAGES)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_MINIMAL)
        original_pyproject = PYPROJECT_MINIMAL

        aggressive_lock = LOCKFILE_TWO_PACKAGES.replace("3.9.5", "4.0.0")
        conservative_lock = LOCKFILE_TWO_PACKAGES.replace("3.9.5", "3.10.0")
        upgrade_call = 0
        validation_call = 0

        def mock_run_command(cmd: list[str], **_kwargs: Any) -> tuple[bool, str]:
            nonlocal upgrade_call
            if cmd[0] == "uv" and "lock" in cmd:
                upgrade_call += 1
                if upgrade_call == 1:
                    lock.write_text(aggressive_lock)
                else:
                    lock.write_text(conservative_lock)
                return True, "ok"
            return True, "ok"

        def mock_validation() -> tuple[bool, str]:
            nonlocal validation_call
            validation_call += 1
            if validation_call == 1:
                return False, "tests failed"
            return True, "all green"

        with (
            patch.object(job, "_run_command", side_effect=mock_run_command),
            patch.object(job, "_run_validation", side_effect=mock_validation),
            patch.object(job, "_git_commit_and_push", return_value=(True, "pushed")),
            patch.object(job, "_lockfile_path", lock),
            patch.object(job, "_pyproject_path", pyproject),
        ):
            result = job.run()

        assert result.success is True
        assert pyproject.read_text() == original_pyproject
