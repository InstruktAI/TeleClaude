"""Behavioral coverage for daemon-control first-run start behavior."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "bin" / "daemon-control.sh"

pytestmark = pytest.mark.timeout(10)


def _run_bash(
    script: str, *, env: dict[str, str] | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    command_env.pop("TELECLAUDE_ENV_PATH", None)
    command_env.pop("TELECLAUDE_CONFIG_PATH", None)
    if env is not None:
        command_env.update(env)
    return subprocess.run(
        ["bash", "-c", script],
        cwd=cwd,
        env=command_env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def _redact(value: str, tmp_path: Path) -> str:
    return value.replace(str(tmp_path), "TMP").replace(str(_REPO_ROOT), "REPO")


def _project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    project_root.mkdir(exist_ok=True)
    return project_root


def _start_script(project_root: Path) -> str:
    return f"""
source "{_SCRIPT}"
PROJECT_ROOT="{project_root}"
SERVICE_PATH="{project_root / "service.file"}"
PLATFORM="linux"
SERVICE_LABEL="teleclaude"
start_daemon
"""


def test_start_daemon_source_does_not_mutate_caller_cwd(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    script = f"""
before="$PWD"
source "{_SCRIPT}"
printf 'before=%s\\nafter=%s\\n' "$before" "$PWD"
"""
    process = _run_bash(script, cwd=tmp_path)

    assert process.returncode == 0
    assert _redact(process.stdout, tmp_path) == snapshot


def test_start_daemon_install_before_start_ordering(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    project_root = _project(tmp_path)
    (project_root / ".env").write_text("ok=1\n", encoding="utf-8")
    (project_root / "config.yml").write_text("computer:\n  name: test\n", encoding="utf-8")
    record = tmp_path / "record.txt"
    script = f"""
PROJECT_ROOT="{project_root}"
source "{_SCRIPT}"
SERVICE_PATH="{project_root / "missing.service"}"
PLATFORM="linux"
SERVICE_LABEL="teleclaude"
install_service() {{ echo install_service >> "{record}"; touch "$SERVICE_PATH"; }}
start_startup_log_stream() {{ echo start_stream >> "{record}"; }}
stop_startup_log_stream() {{ echo stop_stream >> "{record}"; }}
wait_for_daemon() {{ echo wait_for_daemon >> "{record}"; return 0; }}
sudo() {{ echo "sudo $*" >> "{record}"; return 0; }}
start_daemon
"""
    process = _run_bash(script, cwd=tmp_path)

    assert process.returncode == 0
    assert _redact(record.read_text(encoding="utf-8"), tmp_path) == snapshot(name="record")
    assert _redact(process.stdout, tmp_path) == snapshot(name="stdout")


def test_config_missing_default_env(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    project_root = _project(tmp_path)
    (project_root / "config.yml").write_text("computer:\n  name: test\n", encoding="utf-8")
    process = _run_bash(_start_script(project_root), cwd=tmp_path)

    assert {"code": process.returncode, "stdout": process.stdout, "stderr": process.stderr} == snapshot


def test_config_missing_default_config_yml(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    project_root = _project(tmp_path)
    (project_root / ".env").write_text("ok=1\n", encoding="utf-8")
    process = _run_bash(_start_script(project_root), cwd=tmp_path)

    assert {"code": process.returncode, "stdout": process.stdout, "stderr": process.stderr} == snapshot


def test_config_missing_env_override_tilde(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    project_root = _project(tmp_path)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (project_root / ".env").write_text("ok=1\n", encoding="utf-8")
    (project_root / "config.yml").write_text("computer:\n  name: test\n", encoding="utf-8")
    env = os.environ.copy()
    env.update({"HOME": str(fake_home), "TELECLAUDE_ENV_PATH": "~/missing.env"})
    process = _run_bash(_start_script(project_root), env=env, cwd=tmp_path)

    assert {"code": process.returncode, "stdout": process.stdout, "stderr": process.stderr} == snapshot


def test_config_missing_env_override_relative(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    project_root = _project(tmp_path)
    (project_root / ".env").write_text("ok=1\n", encoding="utf-8")
    (project_root / "config.yml").write_text("computer:\n  name: test\n", encoding="utf-8")
    env = os.environ.copy()
    env.update({"TELECLAUDE_ENV_PATH": "does-not-exist/.env"})
    process = _run_bash(_start_script(project_root), env=env, cwd=tmp_path)

    assert {"code": process.returncode, "stdout": process.stdout, "stderr": process.stderr} == snapshot


def test_config_missing_config_yml_override_tilde(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    project_root = _project(tmp_path)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (project_root / ".env").write_text("ok=1\n", encoding="utf-8")
    (project_root / "config.yml").write_text("computer:\n  name: test\n", encoding="utf-8")
    env = os.environ.copy()
    env.update({"HOME": str(fake_home), "TELECLAUDE_CONFIG_PATH": "~/missing.yml"})
    process = _run_bash(_start_script(project_root), env=env, cwd=tmp_path)

    assert {"code": process.returncode, "stdout": process.stdout, "stderr": process.stderr} == snapshot


def test_config_missing_config_yml_override_relative(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    project_root = _project(tmp_path)
    (project_root / ".env").write_text("ok=1\n", encoding="utf-8")
    (project_root / "config.yml").write_text("computer:\n  name: test\n", encoding="utf-8")
    env = os.environ.copy()
    env.update({"TELECLAUDE_CONFIG_PATH": "does-not-exist/config.yml"})
    process = _run_bash(_start_script(project_root), env=env, cwd=tmp_path)

    assert {"code": process.returncode, "stdout": process.stdout, "stderr": process.stderr} == snapshot


def test_config_present_proceeds_normally(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    project_root = _project(tmp_path)
    (project_root / ".env").write_text("ok=1\n", encoding="utf-8")
    (project_root / "config.yml").write_text("computer:\n  name: test\n", encoding="utf-8")
    record = tmp_path / "record.txt"
    script = f"""
PROJECT_ROOT="{project_root}"
source "{_SCRIPT}"
SERVICE_PATH="{project_root / "missing.service"}"
PLATFORM="linux"
SERVICE_LABEL="teleclaude"
install_service() {{ echo install_service >> "{record}"; touch "$SERVICE_PATH"; }}
start_startup_log_stream() {{ echo start_stream >> "{record}"; }}
stop_startup_log_stream() {{ echo stop_stream >> "{record}"; }}
wait_for_daemon() {{ echo wait_for_daemon >> "{record}"; return 0; }}
sudo() {{ echo "sudo $*" >> "{record}"; return 0; }}
start_daemon
"""
    process = _run_bash(script, cwd=tmp_path)

    assert process.returncode == 0
    assert {
        "stdout": _redact(process.stdout, tmp_path),
        "record": _redact(record.read_text(encoding="utf-8"), tmp_path),
    } == snapshot


def test_make_start_public_boundary_missing_config(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    project_root = tmp_path / "project_root"
    project_root.mkdir()
    shutil.copy2(_REPO_ROOT / "Makefile", project_root / "Makefile")
    shutil.copytree(_REPO_ROOT / "bin", project_root / "bin")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env.pop("TELECLAUDE_ENV_PATH", None)
    env.pop("TELECLAUDE_CONFIG_PATH", None)

    process = subprocess.run(
        ["make", "start"],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert {"code": process.returncode, "stdout": process.stdout, "stderr": process.stderr} == snapshot
