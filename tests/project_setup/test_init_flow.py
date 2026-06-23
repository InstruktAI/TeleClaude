"""Functional coverage for project init staying local-only (no remote provisioning).

Remote provisioning is an intelligence-owned agent procedure that consumes the
company profile, not an init-code step. ``init_project`` establishes the local
repository only; it never branches on gh-availability/auth/TTY to add a remote.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from teleclaude.project_setup import init_flow

_SPEC = "project/procedure/init-extensions"


def _seed_python_project(project_root: Path) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "app.py").write_text("print('ready')\n", encoding="utf-8")
    (project_root / "teleclaude.yml").write_text("project_name: Demo Project\n", encoding="utf-8")


def _git(project_root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=project_root, text=True, capture_output=True, check=True)
    return result.stdout.strip()


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-INIT-EXT-1A")
def test_init_project_leaves_repo_local_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After init, the project is a local repo with no ``origin`` remote; setup still completes."""
    project_root = tmp_path / "downstream"
    _seed_python_project(project_root)

    monkeypatch.setattr(init_flow, "sync_project_artifacts", lambda _project_root: None)
    monkeypatch.setattr(init_flow, "deploy_skeleton", lambda _project_root: None)
    monkeypatch.setattr(init_flow, "register_root", lambda *, project_root: None)
    monkeypatch.setattr(init_flow, "seed_event_domains", lambda _project_root: None)
    monkeypatch.setattr(init_flow, "_prompt_release_channel", lambda _project_root: None)

    init_flow.init_project(project_root)

    # The repo exists (local-only) and carries no remotes — remote setup is the
    # agent procedure's job, never init's.
    assert (project_root / ".git").exists()
    assert not _git(project_root, "remote")
