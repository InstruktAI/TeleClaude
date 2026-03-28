# guard: no-companion
# pyright: reportMissingImports=false, reportGeneralTypeIssues=false
"""Test spec (xfail) for watcher service installation and secret management - R3, R4.

Covers secret generation/storage/injection (R3.1-R3.4), macOS launchd
installation (R4.1), Linux systemd installation (R4.2), no coarse OS path
units (R4.3), idempotent installation (R4.5), and one-service-per-project (R4.6).
All tests are marked xfail.
"""
# pylint: disable=import-outside-toplevel,missing-function-docstring,too-few-public-methods,unused-argument

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _redirect_installer_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep installer artifacts and watcher secrets under the per-test temp home."""
    test_home = tmp_path / "home"
    test_home.mkdir()
    monkeypatch.setenv("HOME", str(test_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: test_home))

    from teleclaude.project_setup import todo_watcher_install

    monkeypatch.setattr(
        todo_watcher_install,
        "_WATCHER_SECRET_DIR",
        test_home / ".teleclaude" / "watcher-secrets",
    )


# ---------------------------------------------------------------------------
# R3.1 — Secret Generation
# ---------------------------------------------------------------------------


class TestSecretGeneration:
    """telec init generates a watcher-specific secret for each project."""

    def test_secret_is_generated_during_install(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("darwin"), _mock_subprocess():
            install_todo_watcher(tmp_path)

        secret = _read_stored_secret(tmp_path)
        assert secret is not None
        assert len(secret) > 0

    def test_secret_has_sufficient_entropy(self, tmp_path: Path) -> None:
        """Generated secret must be long enough to resist brute-force."""
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("darwin"), _mock_subprocess():
            install_todo_watcher(tmp_path)

        secret = _read_stored_secret(tmp_path)
        assert secret is not None
        # At least 32 characters of hex/base64 provides adequate entropy
        assert len(secret) >= 32

    def test_each_project_gets_unique_secret(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        project_a = tmp_path / "project-a"
        project_b = tmp_path / "project-b"
        project_a.mkdir()
        project_b.mkdir()

        with _mock_platform("darwin"), _mock_subprocess():
            install_todo_watcher(project_a)
            install_todo_watcher(project_b)

        secret_a = _read_stored_secret(project_a)
        secret_b = _read_stored_secret(project_b)
        assert secret_a != secret_b


# ---------------------------------------------------------------------------
# R3.2 — Secret Storage
# ---------------------------------------------------------------------------


class TestSecretStorage:
    """The secret is stored persistently for daemon verification."""

    def test_secret_persists_across_calls(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("darwin"), _mock_subprocess():
            install_todo_watcher(tmp_path)

        secret_first = _read_stored_secret(tmp_path)

        # Secret must be retrievable without re-running install
        secret_again = _read_stored_secret(tmp_path)
        assert secret_first == secret_again


# ---------------------------------------------------------------------------
# R3.3 — Secret Injection into Service Environment
# ---------------------------------------------------------------------------


class TestSecretInjection:
    """The secret is injected into the OS service environment."""

    def test_launchd_plist_contains_secret_env_var(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("darwin"), _mock_subprocess():
            install_todo_watcher(tmp_path)

        plist_content = _find_plist_content(tmp_path)
        assert plist_content is not None, "No plist file generated"
        # Must inject the secret as an environment variable
        assert "TELECLAUDE_WATCHER_SECRET" in plist_content

    def test_systemd_service_contains_secret_env_var(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("linux"), _mock_subprocess():
            install_todo_watcher(tmp_path)

        service_content = _find_systemd_service_content(tmp_path)
        assert service_content is not None, "No systemd service file generated"
        assert "TELECLAUDE_WATCHER_SECRET" in service_content


# ---------------------------------------------------------------------------
# R3.4 — Rejection on Missing or Invalid Secret
# ---------------------------------------------------------------------------
# (Server-side rejection is tested in test_todo_watcher_route.py R2.1)


# ---------------------------------------------------------------------------
# R4.1 — macOS Installation (launchd)
# ---------------------------------------------------------------------------


class TestMacOSInstallation:
    """On macOS, installs a launchd agent for the todo watcher."""

    def test_creates_launchd_plist(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("darwin"), _mock_subprocess():
            install_todo_watcher(tmp_path)

        plist_content = _find_plist_content(tmp_path)
        assert plist_content is not None

    def test_plist_label_includes_project_identifier(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        project = tmp_path / "my-project"
        project.mkdir()

        with _mock_platform("darwin"), _mock_subprocess():
            install_todo_watcher(project)

        plist_content = _find_plist_content(project)
        assert plist_content is not None
        # Label must be distinguishable per project
        assert "my-project" in plist_content.lower() or "my_project" in plist_content.lower()

    def test_plist_has_keep_alive(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("darwin"), _mock_subprocess():
            install_todo_watcher(tmp_path)

        plist_content = _find_plist_content(tmp_path)
        assert plist_content is not None
        assert "KeepAlive" in plist_content

    def test_plist_has_run_at_load(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("darwin"), _mock_subprocess():
            install_todo_watcher(tmp_path)

        plist_content = _find_plist_content(tmp_path)
        assert plist_content is not None
        assert "RunAtLoad" in plist_content

    def test_launchctl_bootstrap_called(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("darwin"), _mock_subprocess() as sp_mock:
            install_todo_watcher(tmp_path)

        launchctl_calls = [c for c in sp_mock.call_args_list if any("launchctl" in str(a) for a in c.args[0])]
        assert len(launchctl_calls) > 0, "launchctl was never called"


# ---------------------------------------------------------------------------
# R4.2 — Linux Installation (systemd)
# ---------------------------------------------------------------------------


class TestLinuxInstallation:
    """On Linux, installs a systemd --user service for the todo watcher."""

    def test_creates_systemd_service_file(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("linux"), _mock_subprocess():
            install_todo_watcher(tmp_path)

        content = _find_systemd_service_content(tmp_path)
        assert content is not None

    def test_service_has_restart_policy(self, tmp_path: Path) -> None:
        """systemd service must restart on failure (kept alive)."""
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("linux"), _mock_subprocess():
            install_todo_watcher(tmp_path)

        content = _find_systemd_service_content(tmp_path)
        assert content is not None
        assert "Restart=" in content

    def test_systemctl_enable_called(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("linux"), _mock_subprocess() as sp_mock:
            install_todo_watcher(tmp_path)

        systemctl_calls = [c for c in sp_mock.call_args_list if any("systemctl" in str(a) for a in c.args[0])]
        assert len(systemctl_calls) > 0, "systemctl was never called"

    def test_systemd_execstart_uses_watcher_command_for_paths_with_spaces(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import _watcher_command, install_todo_watcher

        project = tmp_path / "project with spaces"
        project.mkdir()

        with _mock_platform("linux"), _mock_subprocess():
            install_todo_watcher(project)

        content = _find_systemd_service_content(project)
        assert content is not None
        assert f"ExecStart={_watcher_command(project.resolve())}" in content


# ---------------------------------------------------------------------------
# R4.3 — No Use of Coarse OS Path Units
# ---------------------------------------------------------------------------


class TestNoCoarsePathUnits:
    """Must not use launchd WatchPaths or systemd.path for todo monitoring."""

    def test_launchd_plist_no_watchpaths(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("darwin"), _mock_subprocess():
            install_todo_watcher(tmp_path)

        plist_content = _find_plist_content(tmp_path)
        assert plist_content is not None
        assert "WatchPaths" not in plist_content

    def test_no_systemd_path_unit_created(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("linux"), _mock_subprocess():
            install_todo_watcher(tmp_path)

        # Must not create a .path unit for todo watching
        path_content = _find_systemd_path_content(tmp_path, prefix="todo")
        assert path_content is None, "systemd .path unit must not be used for todo watching"


# ---------------------------------------------------------------------------
# R4.5 — Idempotent Installation
# ---------------------------------------------------------------------------


class TestIdempotentInstallation:
    """Re-running install replaces the service cleanly."""

    def test_double_install_does_not_duplicate(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("darwin"), _mock_subprocess():
            install_todo_watcher(tmp_path)
            install_todo_watcher(tmp_path)

        plists = _count_plist_files(tmp_path)
        assert plists == 1, f"Expected 1 plist, found {plists}"

    def test_reinstall_bootouts_old_service_first(self, tmp_path: Path) -> None:
        """On macOS, re-install must bootout the old service before bootstrapping new."""
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        with _mock_platform("darwin"), _mock_subprocess() as sp_mock:
            install_todo_watcher(tmp_path)
            install_todo_watcher(tmp_path)

        bootout_calls = [c for c in sp_mock.call_args_list if any("bootout" in str(a) for a in c.args[0])]
        assert len(bootout_calls) >= 1


# ---------------------------------------------------------------------------
# R4.6 — One Service Per Project
# ---------------------------------------------------------------------------


class TestOneServicePerProject:
    """Each project gets its own independent service."""

    def test_different_projects_get_different_services(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        project_a = tmp_path / "project-alpha"
        project_b = tmp_path / "project-beta"
        project_a.mkdir()
        project_b.mkdir()

        with _mock_platform("darwin"), _mock_subprocess():
            install_todo_watcher(project_a)
            install_todo_watcher(project_b)

        plist_a = _find_plist_content(project_a)
        plist_b = _find_plist_content(project_b)
        assert plist_a is not None
        assert plist_b is not None
        # Labels must differ
        assert plist_a != plist_b

    def test_same_basename_paths_get_distinct_service_labels(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import _project_label

        project_a = tmp_path / "alpha" / "app"
        project_b = tmp_path / "beta" / "app"
        project_a.mkdir(parents=True)
        project_b.mkdir(parents=True)

        assert _project_label(project_a) != _project_label(project_b)


class TestIsolation:
    """Installer tests keep filesystem side effects under the test temp directory."""

    def test_installer_artifacts_live_under_test_home(self, tmp_path: Path) -> None:
        from teleclaude.project_setup.todo_watcher_install import install_todo_watcher

        project = tmp_path / "project"
        project.mkdir()

        with _mock_platform("darwin"), _mock_subprocess():
            install_todo_watcher(project)

        launch_agents = tmp_path / "home" / "Library" / "LaunchAgents"
        assert any(launch_agents.glob("ai.instrukt.teleclaude.todo*.plist"))


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _mock_platform(platform: str) -> object:
    return patch("sys.platform", platform)


def _mock_subprocess() -> object:
    return patch("subprocess.run", return_value=MagicMock(returncode=0))


def _read_stored_secret(project_root: Path) -> str | None:
    """Read the stored watcher secret for a project. Implementation-agnostic."""
    try:
        from teleclaude.project_setup.todo_watcher_install import get_watcher_secret

        return get_watcher_secret(project_root)
    except ImportError:
        return None


def _find_plist_content(project_root: Path) -> str | None:
    """Find and read the launchd plist generated for a project's todo watcher."""
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    if not launch_agents.exists():
        # Check if the installer wrote to a mock/test location
        return None
    for plist in launch_agents.glob("ai.instrukt.teleclaude.todo*.plist"):
        content = plist.read_text(encoding="utf-8")
        if str(project_root) in content:
            return content
    return None


def _find_systemd_service_content(project_root: Path) -> str | None:
    """Find and read the systemd service file for a project's todo watcher."""
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    if not unit_dir.exists():
        return None
    for service in unit_dir.glob("teleclaude-todo*.service"):
        content = service.read_text(encoding="utf-8")
        if str(project_root) in content:
            return content
    return None


def _find_systemd_path_content(project_root: Path, prefix: str = "todo") -> str | None:
    """Find systemd .path unit files for todo watching (should not exist)."""
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    if not unit_dir.exists():
        return None
    for path_unit in unit_dir.glob(f"teleclaude-{prefix}*.path"):
        return path_unit.read_text(encoding="utf-8")
    return None


def _count_plist_files(project_root: Path) -> int:
    """Count launchd plist files for todo watchers."""
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    if not launch_agents.exists():
        return 0
    count = 0
    for plist in launch_agents.glob("ai.instrukt.teleclaude.todo*.plist"):
        content = plist.read_text(encoding="utf-8")
        if str(project_root) in content:
            count += 1
    return count
