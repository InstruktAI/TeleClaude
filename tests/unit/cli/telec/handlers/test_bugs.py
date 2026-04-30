from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

bugs = importlib.import_module("teleclaude.cli.telec.handlers.bugs")


def test_handle_bugs_dispatches_create(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[list[str]] = []

    monkeypatch.setattr(bugs, "_handle_bugs_create", received.append)

    bugs._handle_bugs(["create", "sample-bug"])

    assert received == [["sample-bug"]]


def test_handle_bugs_create_calls_dump_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    api_calls: list[tuple[str, str]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        bugs,
        "tool_api_request",
        lambda method, path, **kw: api_calls.append((method, path)) or {"status": "ok", "slug": "sample-bug"},
    )

    bugs._handle_bugs_create(["sample-bug"])

    assert api_calls[0] == ("POST", "/todos/dump")


def test_handle_bugs_report_generates_slug_and_dumps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bugs, "normalize_slug", lambda _text: "example-bug")
    monkeypatch.setattr(bugs, "tool_api_request", lambda *a, **kw: {"status": "ok", "slug": "fix-example-bug"})

    bugs._handle_bugs_report(["Example bug"])

    output = capsys.readouterr().out
    assert "fix-example-bug" in output


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


def test_resolve_project_by_name_unknown_raises_system_exit() -> None:
    cfg = _mock_config_with_dirs(
        [
            _make_trusted_dir("alpha", "/a"),
            _make_trusted_dir("beta", "/b"),
        ]
    )

    with patch("teleclaude.config.config", cfg):
        with pytest.raises(SystemExit):
            bugs._resolve_project_by_name("nonexistent")


def test_handle_bugs_report_with_project_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_path = tmp_path / "target-project"
    project_path.mkdir()

    monkeypatch.setattr(bugs, "normalize_slug", lambda _text: "some-bug")
    monkeypatch.setattr(bugs, "tool_api_request", lambda *a, **kw: {"status": "ok", "slug": "fix-some-bug"})

    cfg = _mock_config_with_dirs([_make_trusted_dir("target", str(project_path))])
    with patch("teleclaude.config.config", cfg):
        bugs._handle_bugs_report(["Some bug", "--project", "target"])

    output = capsys.readouterr().out
    assert "fix-some-bug" in output


def test_handle_bugs_create_with_project_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_path = tmp_path / "target-project"
    project_path.mkdir()

    monkeypatch.setattr(bugs, "tool_api_request", lambda *a, **kw: {"status": "ok", "slug": "my-bug"})

    cfg = _mock_config_with_dirs([_make_trusted_dir("target", str(project_path))])
    with patch("teleclaude.config.config", cfg):
        bugs._handle_bugs_create(["my-bug", "--project", "target"])

    assert "Created bug: my-bug" in capsys.readouterr().out


def test_handle_bugs_list_queries_db_for_bug_kind_todos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bug list queries todos.db for kind=bug todos and derives status from build_review verdict."""
    monkeypatch.chdir(tmp_path)

    # Set up a minimal todos.db with a bug-kind todo
    db_dir = tmp_path / ".teleclaude"
    db_dir.mkdir()
    db_path = db_dir / "todos.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE roadmap (id TEXT PRIMARY KEY, slug TEXT, position INT, "
        "group_slug TEXT, description TEXT, status TEXT, delivered_at TEXT, "
        "delivered_commit TEXT, children TEXT, created_at TEXT, updated_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE todo_state (id TEXT PRIMARY KEY, slug TEXT, state TEXT, created_at TEXT, updated_at TEXT)"
    )
    conn.execute(
        "INSERT INTO roadmap (id, slug, position, status, created_at, updated_at) "
        "VALUES ('id1', 'fix-crash', 1, 'active', '', '')"
    )
    state = json.dumps({"kind": "bug", "phase": "review_pending", "build_review": {"verdict": "changes_requested"}})
    conn.execute(
        "INSERT INTO todo_state (id, slug, state, created_at, updated_at) VALUES ('id1', 'fix-crash', ?, '', '')",
        (state,),
    )
    conn.commit()
    conn.close()

    # Mock get_todos_db_sync via the consumer-module local name
    mock_db = MagicMock()
    mock_db._sync_conn.return_value = sqlite3.connect(str(db_path))

    monkeypatch.setattr(
        "teleclaude.cli.telec.handlers.bugs.get_todos_db_sync",
        lambda _cwd: mock_db,
    )

    bugs._handle_bugs_list([])

    output = capsys.readouterr().out
    assert "fix-crash" in output
    assert "fixing" in output
