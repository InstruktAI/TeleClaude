"""Functional coverage for format delegation path safety."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from teleclaude.cli.telec.handlers import quality

_SPEC = "general/spec/tools/telec-cli"
_FILES_FROM_PREFIX = "FILES_FROM="
_PROJECT_ROOT_SENTINEL = "<project-root>"


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_format_passes_adversarial_paths_through_nul_files_from(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    records: list[object] = []

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
def test_format_propagates_make_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    records: list[object] = []

    monkeypatch.setattr(quality, "resolve_invocation_cwd", lambda: tmp_path)
    monkeypatch.setattr(quality, "resolve_git_root", lambda _cwd: tmp_path)

    def fake_popen(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        files_from = next(part.removeprefix(_FILES_FROM_PREFIX) for part in cmd if part.startswith(_FILES_FROM_PREFIX))
        records.append(("make", cmd[:2], _PROJECT_ROOT_SENTINEL, Path(files_from).read_bytes().split(b"\0")))
        return SimpleNamespace(wait=lambda: 9)

    monkeypatch.setattr(quality.subprocess, "Popen", fake_popen)

    with pytest.raises(SystemExit) as exc:
        quality.handle_format(["teleclaude/core.py"])

    assert exc.value.code == 9
    assert {"records": records} == snapshot
