from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

todo_handler = importlib.import_module("teleclaude.cli.telec.handlers.todo")


@pytest.fixture
def mock_ensure_pushed():
    with patch("teleclaude.core.next_machine.worktrees._ensure_todo_on_remote_main") as mock:
        mock.return_value = (True, "pushed")
        yield mock


@pytest.fixture
def mock_commit_bookkeeping():
    with patch("teleclaude.core.next_machine.worktrees.commit_bookkeeping_to_main") as mock:
        mock.return_value = (True, "committed")
        yield mock


def test_handle_todo_dump_pushes_to_remote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mock_commit_bookkeeping: MagicMock, mock_ensure_pushed: MagicMock
) -> None:
    todo_dir = tmp_path / "todos" / "sample-dump"

    def fake_skeleton(*_args: object, **_kwargs: object) -> Path:
        todo_dir.mkdir(parents=True, exist_ok=True)
        return todo_dir

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(todo_handler, "create_todo_skeleton", fake_skeleton)
    monkeypatch.setattr(todo_handler, "tool_api_request", MagicMock())

    todo_handler._handle_todo_dump(["sample-dump", "content"])

    mock_ensure_pushed.assert_called_once_with(str(tmp_path), "sample-dump")


def test_handle_todo_split_pushes_parent_and_children(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mock_ensure_pushed: MagicMock
) -> None:
    monkeypatch.chdir(tmp_path)
    import teleclaude.todo_scaffold as scaffold

    monkeypatch.setattr(scaffold, "split_todo", lambda root, slug, children: [tmp_path / "todos" / c for c in children])  # pyright: ignore[reportUnknownLambdaType]

    todo_handler._handle_todo_split(["parent", "--into", "child-a", "--into", "child-b"])

    assert mock_ensure_pushed.call_count == 3
    mock_ensure_pushed.assert_any_call(str(tmp_path), "parent")
    mock_ensure_pushed.assert_any_call(str(tmp_path), "child-a")
    mock_ensure_pushed.assert_any_call(str(tmp_path), "child-b")


def test_handle_todo_validate_calls_single_slug_validator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            sys.modules,
            "teleclaude.resource_validation",
            SimpleNamespace(validate_all_todos=lambda _root: ["unexpected"], validate_todo=lambda slug, root: []),  # pyright: ignore[reportUnknownLambdaType]
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
                is_bug_todo=lambda cwd, slug: False,  # pyright: ignore[reportUnknownLambdaType]
                verify_artifacts=lambda cwd, slug, phase, *, is_bug: (True, f"{slug}:{phase}:{is_bug}"),  # pyright: ignore[reportUnknownLambdaType]
            ),
        )
        with pytest.raises(SystemExit) as exc_info:
            todo_handler._handle_todo_verify_artifacts(["sample", "--phase", "build"])

    assert exc_info.value.code == 0
    assert "sample:build:False" in capsys.readouterr().out


def test_handle_todo_dump_writes_input_and_emits_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mock_commit_bookkeeping: MagicMock, mock_ensure_pushed: MagicMock
) -> None:
    emitted = MagicMock()
    logger = MagicMock()
    todo_dir = tmp_path / "todos" / "sample"

    def fake_skeleton(*_args: object, **_kwargs: object) -> Path:
        todo_dir.mkdir(parents=True, exist_ok=True)
        return todo_dir

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(todo_handler, "create_todo_skeleton", fake_skeleton)
    monkeypatch.setattr(todo_handler, "tool_api_request", emitted)
    monkeypatch.setattr(todo_handler, "get_logger", lambda _name: logger)  # pyright: ignore[reportUnknownLambdaType]

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
            sys.modules,
            "teleclaude.todo_scaffold",
            SimpleNamespace(split_todo=lambda root, slug, children: created),  # pyright: ignore[reportUnknownLambdaType]
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
            SimpleNamespace(remove_todo=lambda project_root, slug: removed.append((project_root, slug))),  # pyright: ignore[reportUnknownLambdaType]
        )
        todo_handler._handle_todo_remove(["sample"])

    assert removed == [(tmp_path, "sample")]
    assert "Removed todo: sample" in capsys.readouterr().out


def test_handle_todo_dump_idempotent_retry_skips_skeleton(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mock_commit_bookkeeping: MagicMock, mock_ensure_pushed: MagicMock
) -> None:
    """Re-running dump with same content skips skeleton creation."""
    todo_dir = tmp_path / "todos" / "retry-slug"
    todo_dir.mkdir(parents=True)
    # Write the exact content the handler would produce
    (todo_dir / "input.md").write_text("# retry-slug — Input\n\nsame content\n", encoding="utf-8")

    skeleton_called = False

    def fail_skeleton(*_args: object, **_kwargs: object) -> Path:
        nonlocal skeleton_called
        skeleton_called = True
        raise AssertionError("create_todo_skeleton should not be called on retry")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(todo_handler, "create_todo_skeleton", fail_skeleton)
    monkeypatch.setattr(todo_handler, "tool_api_request", MagicMock())

    todo_handler._handle_todo_dump(["retry-slug", "same content"])

    assert not skeleton_called
    mock_commit_bookkeeping.assert_called_once()


def test_handle_todo_dump_collision_different_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Dump to existing slug with different content is a hard error."""
    todo_dir = tmp_path / "todos" / "taken-slug"
    todo_dir.mkdir(parents=True)
    (todo_dir / "input.md").write_text("# taken-slug — Input\n\nold content\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        todo_handler._handle_todo_dump(["taken-slug", "new content"])

    assert exc_info.value.code == 1
    assert "different content" in capsys.readouterr().out


def test_handle_todo_dump_index_lock_fails_with_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Index lock returns actionable error with recovery instructions."""
    todo_dir = tmp_path / "todos" / "lock-slug"

    def fake_skeleton(*_args: object, **_kwargs: object) -> Path:
        todo_dir.mkdir(parents=True, exist_ok=True)
        return todo_dir

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(todo_handler, "create_todo_skeleton", fake_skeleton)

    with patch("teleclaude.core.next_machine.worktrees.commit_bookkeeping_to_main") as mock_commit:
        mock_commit.return_value = (False, "index_locked")
        with pytest.raises(SystemExit) as exc_info:
            todo_handler._handle_todo_dump(["lock-slug", "content"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "index.lock" in output
    assert "rm" in output
    assert "idempotent" in output
