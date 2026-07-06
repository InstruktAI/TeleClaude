"""Functional coverage for jscpd leg exclusion from scoped `tools/quality.sh` runs."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QUALITY_SCRIPT = _REPO_ROOT / "tools" / "quality.sh"


def _write_executable(path: Path, script: str) -> None:
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _stub_bin(tmp_path: Path, jscpd_sentinel: Path) -> Path:
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    _write_executable(stub_bin / "uv", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(stub_bin / "pnpm", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(
        stub_bin / "npx",
        f'#!/usr/bin/env bash\ncase "$*" in\n  *jscpd*) touch "{jscpd_sentinel}" ;;\nesac\nexit 0\n',
    )
    return stub_bin


def _run_quality_lint(tmp_path: Path, *, files_from: Path | None) -> tuple[int, Path]:
    jscpd_sentinel = tmp_path / "jscpd-ran"
    stub_bin = _stub_bin(tmp_path, jscpd_sentinel)
    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}{os.pathsep}{env['PATH']}"
    if files_from is not None:
        env["FILES_FROM"] = str(files_from)
    else:
        env.pop("FILES_FROM", None)
    result = subprocess.run(
        ["bash", str(_QUALITY_SCRIPT), "lint"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=4,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.returncode, jscpd_sentinel


@pytest.mark.functional
def test_scoped_python_lint_excludes_jscpd_leg(tmp_path: Path) -> None:
    files_from = tmp_path / "files-from"
    files_from.write_bytes(b"teleclaude/__init__.py\0")

    _, jscpd_sentinel = _run_quality_lint(tmp_path, files_from=files_from)

    assert not jscpd_sentinel.exists()


@pytest.mark.functional
def test_scoped_config_triggered_full_python_lint_excludes_jscpd_leg(tmp_path: Path) -> None:
    files_from = tmp_path / "files-from"
    files_from.write_bytes(b"pyproject.toml\0")

    _, jscpd_sentinel = _run_quality_lint(tmp_path, files_from=files_from)

    assert not jscpd_sentinel.exists()


@pytest.mark.functional
def test_full_lint_runs_jscpd_leg(tmp_path: Path) -> None:
    _, jscpd_sentinel = _run_quality_lint(tmp_path, files_from=None)

    assert jscpd_sentinel.exists()
