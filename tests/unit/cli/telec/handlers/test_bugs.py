from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

bugs = importlib.import_module("teleclaude.cli.telec.handlers.bugs")


def _close_and_return(value: object) -> Callable[[object], object]:
    def _runner(coro: object) -> object:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return value

    return _runner


def test_handle_bugs_dispatches_create(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[list[str]] = []

    monkeypatch.setattr(bugs, "_handle_bugs_create", lambda args: received.append(args))

    bugs._handle_bugs(["create", "sample-bug"])

    assert received == [["sample-bug"]]


def test_handle_bugs_create_scaffolds_bug(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    created_dir = tmp_path / "todos" / "sample-bug"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bugs, "create_bug_skeleton", lambda **kwargs: created_dir)

    bugs._handle_bugs_create(["sample-bug"])

    assert str(created_dir) in capsys.readouterr().out


def test_handle_bugs_report_generates_slug_and_dispatches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    todo_dir = tmp_path / "todos" / "fix-example-bug"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bugs, "normalize_slug", lambda _text: "example-bug")
    monkeypatch.setattr(bugs, "create_bug_skeleton", lambda *args, **kwargs: todo_dir)
    monkeypatch.setattr(bugs.asyncio, "run", _close_and_return(SimpleNamespace(session_id="sess-123")))

    bugs._handle_bugs_report(["Example bug"])

    output = capsys.readouterr().out
    assert "fix-example-bug" in output
    assert "sess-123" in output


def test_handle_bugs_list_uses_worktree_state_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    slug = "sample-bug"
    todo_dir = tmp_path / "todos" / slug
    todo_dir.mkdir(parents=True)
    (todo_dir / "bug.md").write_text("# bug\n", encoding="utf-8")
    (todo_dir / "state.yaml").write_text("build: pending\nreview: pending\n", encoding="utf-8")

    worktree_state = tmp_path / bugs.WORKTREE_DIR / slug / "todos" / slug / "state.yaml"
    worktree_state.parent.mkdir(parents=True)
    worktree_state.write_text("build: complete\nreview: changes_requested\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    bugs._handle_bugs_list([])

    output = capsys.readouterr().out
    assert slug in output
    assert "fixing" in output
