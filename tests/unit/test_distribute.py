"""Characterization and regression tests for scripts/distribute.py."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DISTRIBUTE_SCRIPT = _REPO_ROOT / "scripts" / "distribute.py"


def _import_distribute():
    spec = importlib.util.spec_from_file_location("distribute", _DISTRIBUTE_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    original_path = sys.path[:]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = original_path
    return mod


def test_expand_exec_directives_prepends_repo_venv_to_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    distribute = _import_distribute()
    project_bin = str(tmp_path / ".venv" / "bin")
    repo_bin = str(_REPO_ROOT / ".venv" / "bin")

    def fake_run(_cmd: str, **kwargs: object) -> SimpleNamespace:
        env = kwargs.get("env")
        assert isinstance(env, dict)
        assert isinstance(env.get("PATH"), str)
        path_entries = env["PATH"].split(os.pathsep)
        assert path_entries[:2] == [project_bin, repo_bin]
        return SimpleNamespace(returncode=0, stdout="telec help", stderr="")

    monkeypatch.setattr(distribute.subprocess, "run", fake_run)

    rendered = distribute.expand_exec_directives("<!-- @exec: telec -h -->", project_root=tmp_path)

    assert "telec help" in rendered
