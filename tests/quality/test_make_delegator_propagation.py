"""Functional coverage for telec code make delegation."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict

import pytest

from teleclaude.cli.telec.handlers import quality

_SPEC = "general/spec/tools/telec-cli"
_FILES_FROM_PREFIX = "FILES_FROM="
_PROJECT_ROOT_SENTINEL = "<project-root>"


class _MakeRecord(TypedDict):
    cmd: list[str]
    cwd: str
    files: list[bytes]


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_format_passes_adversarial_paths_through_nul_files_from(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    records: list[_MakeRecord] = []

    monkeypatch.setattr(quality, "resolve_invocation_cwd", lambda: tmp_path)
    monkeypatch.setattr(quality, "resolve_git_root", lambda _cwd: tmp_path)

    def fake_popen(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        files_from = next(part.removeprefix(_FILES_FROM_PREFIX) for part in cmd if part.startswith(_FILES_FROM_PREFIX))
        records.append(
            {
                "cmd": cmd[:2],
                "cwd": _PROJECT_ROOT_SENTINEL,
                "files": Path(files_from).read_bytes().split(b"\0"),
            }
        )
        return SimpleNamespace(wait=lambda: 0)

    monkeypatch.setattr(quality.subprocess, "Popen", fake_popen)

    quality.handle_format(["a b.py", "c;d.py"])

    assert {"records": records} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_test_update_snapshots_forwards_make_variable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    records: list[object] = []

    monkeypatch.setattr(quality, "resolve_invocation_cwd", lambda: tmp_path)
    monkeypatch.setattr(quality, "resolve_git_root", lambda _cwd: tmp_path)

    def fake_popen(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        records.append((cmd, "<project-root>"))
        return SimpleNamespace(wait=lambda: 0)

    monkeypatch.setattr(quality.subprocess, "Popen", fake_popen)

    quality.handle_test(["--update-snapshots"])

    assert {"records": records} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "path-safety")
def test_lint_rejects_leading_dash_paths_before_make(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quality, "resolve_invocation_cwd", lambda: tmp_path)
    monkeypatch.setattr(quality, "resolve_git_root", lambda _cwd: tmp_path)

    with pytest.raises(SystemExit):
        quality.handle_lint(["-bad.py"])


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_test_handler_teardown_kills_sigterm_ignoring_make_descendant(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    child_code = (
        "import os, signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"open({str(child_pid_file)!r}, 'w', encoding='utf-8').write(str(os.getpid())); "
        "time.sleep(30)"
    )
    (tmp_path / "Makefile").write_text(f"test:\n\t@{shlex.quote(sys.executable)} -c {child_code!r} & wait\n")
    runner_code = (
        "from pathlib import Path; "
        "from teleclaude.cli.telec.handlers import quality; "
        f"project_root = Path({str(tmp_path)!r}); "
        "quality.resolve_invocation_cwd = lambda: project_root; "
        "quality.resolve_git_root = lambda _cwd: project_root; "
        "quality.handle_test([])"
    )

    runner = subprocess.Popen([sys.executable, "-c", runner_code])
    try:
        deadline = time.monotonic() + 5
        while not child_pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child_pid_file.exists()

        child_pid = int(child_pid_file.read_text(encoding="utf-8"))
        runner.terminate()
        assert runner.wait(timeout=4) == -signal.SIGTERM

        deadline = time.monotonic() + 1
        while _pid_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.02)

        assert not _pid_exists(child_pid)
    finally:
        if runner.poll() is None:
            runner.kill()
        if child_pid_file.exists():
            child_pid = int(child_pid_file.read_text(encoding="utf-8"))
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
