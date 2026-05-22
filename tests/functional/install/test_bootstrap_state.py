"""Bootstrap target state snapshots."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType
from typing import TypedDict

import pytest
from syrupy.assertion import SnapshotAssertion

pytestmark = pytest.mark.timeout(25)


type _Inventory = dict[str, list[tuple[str, str, int | str]]]


class _BootstrapState(TypedDict):
    returncode: int
    home: _Inventory
    stub_logs: dict[str, list[str]]
    venv: _Inventory
    project_outputs: dict[str, bool]


def _sandbox_module() -> ModuleType:
    helper_path = Path(__file__).with_name("test_install_sh_responsibility.py")
    spec = importlib.util.spec_from_file_location("install_responsibility_helpers", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load install test helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_stub_logs(stub_log: Path, tmp_path: Path) -> dict[str, list[str]]:
    logs: dict[str, list[str]] = {}
    if not stub_log.exists():
        return logs
    for path in sorted(stub_log.glob("*.log")):
        logs[path.name] = [line.replace(str(tmp_path), "TMP") for line in path.read_text(encoding="utf-8").splitlines()]
    return logs


def _run_bootstrap(target: str, tmp_path: Path) -> _BootstrapState:
    sandbox = _sandbox_module()
    project_root = sandbox._copy_checkout(tmp_path)
    env = sandbox._sandbox_env(tmp_path)
    process = subprocess.run(
        ["make", target],
        cwd=project_root,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    fake_home = Path(env["HOME"])
    stub_log = Path(env["STUB_LOG"])
    home_inventory = {
        ".local/bin": sandbox._inventory(fake_home / ".local" / "bin"),
        ".teleclaude": sandbox._inventory(fake_home / ".teleclaude"),
        ".claude": sandbox._inventory(fake_home / ".claude"),
        ".codex": sandbox._inventory(fake_home / ".codex"),
        ".gemini": sandbox._inventory(fake_home / ".gemini"),
        "Applications": sandbox._inventory(fake_home / "Applications"),
    }
    return {
        "returncode": process.returncode,
        "home": sandbox._redact_inventory(home_inventory, tmp_path),
        "stub_logs": _read_stub_logs(stub_log, tmp_path),
        "venv": sandbox._redact_inventory(
            {"project_venv": sandbox._inventory(project_root / ".venv")},
            tmp_path,
        ),
        "project_outputs": {
            ".env": (project_root / ".env").exists(),
            "config.yml": (project_root / "config.yml").exists(),
            "teleclaude.yml": (project_root / "teleclaude.yml").exists(),
            "bin/teleclaude-wrapper.sh": (project_root / "bin" / "teleclaude-wrapper.sh").exists(),
        },
    }


def test_bootstrap_target_creates_expected_state(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    assert _run_bootstrap("bootstrap", tmp_path) == snapshot


def test_bootstrap_ci_target_preserves_current_tooling_state(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    assert _run_bootstrap("bootstrap-ci", tmp_path) == snapshot
