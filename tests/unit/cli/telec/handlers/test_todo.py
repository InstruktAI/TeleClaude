from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

todo_handler = importlib.import_module("teleclaude.cli.telec.handlers.todo")


def test_handle_todo_routes_scaffold_create(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[list[str]] = []

    monkeypatch.setattr(todo_handler, "_handle_todo_create", lambda args: received.append(args))

    todo_handler._handle_todo(["scaffold", "sample"])

    assert received == [["sample"]]


def test_handle_todo_validate_calls_single_slug_validator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            sys.modules,
            "teleclaude.resource_validation",
            SimpleNamespace(validate_all_todos=lambda _root: ["unexpected"], validate_todo=lambda slug, root: []),
        )
        todo_handler._handle_todo_validate(["sample"])

    assert "sample" in capsys.readouterr().out


def test_handle_todo_verify_artifacts_exits_with_phase_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            sys.modules,
            "teleclaude.core.next_machine.core",
            SimpleNamespace(
                is_bug_todo=lambda cwd, slug: False,
                verify_artifacts=lambda cwd, slug, phase, *, is_bug: (True, f"{slug}:{phase}:{is_bug}"),
            ),
        )
        with pytest.raises(SystemExit) as exc_info:
            todo_handler._handle_todo_verify_artifacts(["sample", "--phase", "build"])

    assert exc_info.value.code == 0
    assert "sample:build:False" in capsys.readouterr().out


def test_handle_todo_dump_writes_input_and_emits_event(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    emitted = MagicMock()
    logger = MagicMock()
    todo_dir = tmp_path / "todos" / "sample"
    todo_dir.mkdir(parents=True)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(todo_handler, "create_todo_skeleton", lambda *args, **kwargs: todo_dir)
    monkeypatch.setattr(todo_handler, "tool_api_request", emitted)
    monkeypatch.setattr(todo_handler, "get_logger", lambda _name: logger)

    todo_handler._handle_todo_dump(["sample", "brain dump", "--after", "dep-a,dep-b"])

    assert "brain dump" in (todo_dir / "input.md").read_text(encoding="utf-8")
    emitted.assert_called_once()
    logger.info.assert_called_once()


def test_handle_todo_split_passes_children_to_scaffold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    created = [tmp_path / "todos" / "child-a", tmp_path / "todos" / "child-b"]

    monkeypatch.chdir(tmp_path)
    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            sys.modules, "teleclaude.todo_scaffold", SimpleNamespace(split_todo=lambda root, slug, children: created)
        )
        todo_handler._handle_todo_split(["parent", "--into", "child-a", "--into", "child-b"])

    output = capsys.readouterr().out
    assert "parent" in output
    assert "child-a" in output


def test_handle_todo_remove_delegates_to_scaffold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    removed: list[tuple[Path, str]] = []

    monkeypatch.chdir(tmp_path)
    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            sys.modules,
            "teleclaude.todo_scaffold",
            SimpleNamespace(remove_todo=lambda project_root, slug: removed.append((project_root, slug))),
        )
        todo_handler._handle_todo_remove(["sample"])

    assert removed == [(tmp_path, "sample")]
    assert "Removed todo: sample" in capsys.readouterr().out
