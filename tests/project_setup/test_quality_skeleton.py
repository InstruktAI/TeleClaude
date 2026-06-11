"""Functional coverage for downstream quality skeleton setup."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from teleclaude.project_setup import init_flow
from teleclaude.project_setup.skeleton import deploy_skeleton

_SPEC = "general/spec/tools/telec-cli"
_INSTALL_PYTHON_TOKEN = "INSTALL_PYTHON"
_PRECOMMIT_PATH = Path(".githooks") / "pre-commit"


def _seed_python_project(project_root: Path) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "app.py").write_text("print('ready')\n", encoding="utf-8")
    (project_root / "teleclaude.yml").write_text("project_name: Demo Project\n", encoding="utf-8")


def _git(project_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "project-setup-quality-skeleton")
def test_python_quality_skeleton_creates_nested_hook_material(
    tmp_path: Path,
    snapshot: object,
) -> None:
    project_root = tmp_path / "downstream"
    _seed_python_project(project_root)

    deploy_skeleton(project_root)

    hook_path = project_root / _PRECOMMIT_PATH
    assert hook_path.is_file()
    assert (hook_path.stat().st_mode & stat.S_IXUSR) == 0
    assert (project_root / "Makefile").is_file()
    assert (project_root / "pyproject.toml").is_file()
    assert (project_root / ".pre-commit-config.yaml").is_file()
    assert {
        "contains_install_python": _INSTALL_PYTHON_TOKEN in hook_path.read_text(encoding="utf-8"),
        "created_parent": hook_path.parent.is_dir(),
        "hook_path": hook_path.relative_to(project_root).as_posix(),
    } == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "project-setup-quality-skeleton")
def test_projects_init_installs_thin_precommit_hook_without_legacy_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "downstream"
    _seed_python_project(project_root)

    monkeypatch.setattr(init_flow, "sync_project_artifacts", lambda _project_root: None)
    monkeypatch.setattr(init_flow, "register_root", lambda *, project_root: None)
    monkeypatch.setattr(init_flow, "seed_event_domains", lambda _project_root: None)

    init_flow.init_project(project_root)

    hook_destination = project_root / _git(project_root, "rev-parse", "--git-path", "hooks/pre-commit")
    hook_content = hook_destination.read_text(encoding="utf-8")
    assert hook_destination.is_file()
    assert hook_destination.stat().st_mode & stat.S_IXUSR
    assert {
        "contains_install_python": _INSTALL_PYTHON_TOKEN in hook_content,
        "destination": hook_destination.relative_to(project_root).as_posix(),
        "matches_project_hook": hook_content == (project_root / _PRECOMMIT_PATH).read_text(encoding="utf-8"),
    } == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "project-setup-quality-skeleton")
def test_generated_python_project_make_install_lint_and_test_smoke_without_network(
    tmp_path: Path,
    snapshot: object,
) -> None:
    project_root = tmp_path / "downstream"
    fake_bin = tmp_path / "bin"
    uv_log = tmp_path / "uv.log"
    _seed_python_project(project_root)
    deploy_skeleton(project_root)
    _git(project_root, "init")

    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        '#!/usr/bin/env sh\nprintf \'%s\\n\' "$*" >> "$UV_LOG"\nexit 0\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["UV_LOG"] = str(uv_log)

    result = subprocess.run(
        ["make", "install", "lint", "test"],
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    hook_destination = project_root / _git(project_root, "rev-parse", "--git-path", "hooks/pre-commit")
    assert result.returncode == 0
    assert hook_destination.is_file()
    assert {
        "hook_contains_install_python": _INSTALL_PYTHON_TOKEN in hook_destination.read_text(encoding="utf-8"),
        "uv_invocations": uv_log.read_text(encoding="utf-8").splitlines(),
    } == snapshot
