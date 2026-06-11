"""Functional coverage for telec code make delegation."""

from __future__ import annotations

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

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        files_from = next(part.removeprefix(_FILES_FROM_PREFIX) for part in cmd if part.startswith(_FILES_FROM_PREFIX))
        records.append(
            {
                "cmd": cmd[:2],
                "cwd": _PROJECT_ROOT_SENTINEL,
                "files": Path(files_from).read_bytes().split(b"\0"),
            }
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(quality.subprocess, "run", fake_run)

    quality.handle_format(["a b.py", "c;d.py"])

    assert {"records": records} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_lint_runs_make_then_guardrails_and_propagates_native_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    records: list[object] = []

    monkeypatch.setattr(quality, "resolve_invocation_cwd", lambda: tmp_path)
    monkeypatch.setattr(quality, "resolve_git_root", lambda _cwd: tmp_path)

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        files_from = next(part.removeprefix(_FILES_FROM_PREFIX) for part in cmd if part.startswith(_FILES_FROM_PREFIX))
        records.append(("make", cmd[:2], _PROJECT_ROOT_SENTINEL, Path(files_from).read_bytes().split(b"\0")))
        return SimpleNamespace(returncode=7)

    class FakeLintRunner:
        def __init__(self, project_root: Path) -> None:
            self.project_root = project_root

        def run(self, *, files: list[str] | None = None, run_all: bool = False) -> None:
            records.append(("guardrails", _PROJECT_ROOT_SENTINEL, self.project_root == tmp_path, files, run_all))

    monkeypatch.setattr(quality.subprocess, "run", fake_run)
    monkeypatch.setattr(quality, "LintRunner", FakeLintRunner)

    with pytest.raises(SystemExit) as exc:
        quality.handle_lint(["teleclaude/core.py"])

    assert exc.value.code == 7
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

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        records.append((cmd, "<project-root>"))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(quality.subprocess, "run", fake_run)

    quality.handle_test(["--update-snapshots"])

    assert {"records": records} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "path-safety")
def test_lint_rejects_leading_dash_paths_before_make(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quality, "resolve_invocation_cwd", lambda: tmp_path)
    monkeypatch.setattr(quality, "resolve_git_root", lambda _cwd: tmp_path)

    with pytest.raises(SystemExit):
        quality.handle_lint(["-bad.py"])
