from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
