from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

bugs = importlib.import_module("teleclaude.cli.telec.handlers.bugs")


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


def test_handle_bugs_create_pushes_to_remote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mock_ensure_pushed: MagicMock
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bugs, "create_bug_skeleton", lambda **kwargs: tmp_path / "todos" / "sample-bug")

    bugs._handle_bugs_create(["sample-bug"])

    mock_ensure_pushed.assert_called_once_with(str(tmp_path), "sample-bug")


def test_handle_bugs_report_pushes_to_remote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mock_commit_bookkeeping: MagicMock
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bugs, "normalize_slug", lambda _text: "sample-bug")
    monkeypatch.setattr(bugs, "create_bug_skeleton", lambda *args, **kwargs: tmp_path / "todos" / "fix-sample-bug")

    # Mock asyncio.run to avoid real API calls
    import asyncio

    async_run = MagicMock()
    async_run.return_value = SimpleNamespace(session_id="sess-123")
    monkeypatch.setattr(asyncio, "run", async_run)

    bugs._handle_bugs_report(["Sample bug"])

    mock_commit_bookkeeping.assert_called_once()


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


def _make_trusted_dir(name: str, path: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, desc="", path=path)


def _mock_config_with_dirs(dirs: list[SimpleNamespace]) -> SimpleNamespace:
    computer = SimpleNamespace(get_all_trusted_dirs=lambda: dirs)
    return SimpleNamespace(computer=computer)


def test_resolve_project_by_name_matches_case_insensitive(tmp_path: Path) -> None:
    target = str(tmp_path / "my-project")
    cfg = _mock_config_with_dirs([_make_trusted_dir("MyProject", target)])

    with patch("teleclaude.config.config", cfg):
        result = bugs._resolve_project_by_name("myproject")

    assert result == Path(target)


def test_resolve_project_by_name_unknown_lists_available(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = _mock_config_with_dirs(
        [
            _make_trusted_dir("alpha", "/a"),
            _make_trusted_dir("beta", "/b"),
        ]
    )

    with patch("teleclaude.config.config", cfg):
        with pytest.raises(SystemExit):
            bugs._resolve_project_by_name("nonexistent")

    output = capsys.readouterr().out
    assert "Unknown project 'nonexistent'" in output
    assert "alpha" in output
    assert "beta" in output


def test_handle_bugs_report_with_project_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_path = tmp_path / "target-project"
    project_path.mkdir()
    todo_dir = project_path / "todos" / "fix-some-bug"

    monkeypatch.setattr(bugs, "normalize_slug", lambda _text: "some-bug")
    monkeypatch.setattr(bugs, "create_bug_skeleton", lambda *args, **kwargs: todo_dir)
    monkeypatch.setattr(bugs.asyncio, "run", _close_and_return(SimpleNamespace(session_id="sess-456")))

    cfg = _mock_config_with_dirs([_make_trusted_dir("target", str(project_path))])
    with patch("teleclaude.config.config", cfg):
        bugs._handle_bugs_report(["Some bug", "--project", "target"])

    output = capsys.readouterr().out
    assert "fix-some-bug" in output
    assert "sess-456" in output


def test_handle_bugs_create_with_project_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_path = tmp_path / "target-project"
    project_path.mkdir()
    created_dir = project_path / "todos" / "my-bug"

    monkeypatch.setattr(bugs, "create_bug_skeleton", lambda **kwargs: created_dir)

    cfg = _mock_config_with_dirs([_make_trusted_dir("target", str(project_path))])
    with patch("teleclaude.config.config", cfg):
        bugs._handle_bugs_create(["my-bug", "--project", "target"])

    assert str(created_dir) in capsys.readouterr().out


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
