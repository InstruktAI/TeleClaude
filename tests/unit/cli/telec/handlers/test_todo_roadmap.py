"""Tests for todo-owned roadmap verbs."""

from __future__ import annotations

import asyncio
import importlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import select
from syrupy.assertion import SnapshotAssertion

from teleclaude.api_models import TodoDTO
from teleclaude.constants import RoadmapStatus
from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db._models import TodoRoadmap

todo = importlib.import_module("teleclaude.cli.telec.handlers.todo")

_ACTIVE_SLUG = "active-item"
_ICEBOX_SLUG = "icebox-item"
_DELIVERED_SLUG = "delivered-item"
_DEPENDENCY_SLUG = "dependency-item"
_COMMIT_HASH = "abc123"
_PROJECT_DIR = "project"
_TODO_STATE = {"schema_version": 2, "kind": "todo", "phase": "in_progress", "lifecycle_phase": "prepared"}
_READY_SINCE = "2026-05-20T00:00:00+00:00"
_SINCE_DAYS = "7d"
_SINCE_ISO = "2026-05-01"


def _make_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "main"
    worktree = tmp_path / "trees" / "sample"
    gitdir = repo_root / ".git" / "worktrees" / "sample"
    gitdir.mkdir(parents=True)
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    return repo_root, worktree


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / _PROJECT_DIR
    project.mkdir()
    return project


def _database(project: Path) -> TodosDb:
    return TodosDb(str(project / ".teleclaude" / "todos.db"))


def _entry_status(database: TodosDb, slug: str) -> tuple[str, str | None]:
    with database._sync_session() as session:
        entry = session.exec(select(TodoRoadmap).where(TodoRoadmap.slug == slug).limit(1)).one()
        return entry.status, entry.ready_since


def _sample_todo(slug: str, status: RoadmapStatus, *, delivered_at: str | None = None) -> TodoDTO:
    return TodoDTO(
        slug=slug,
        status=status,
        description=slug,
        has_requirements=False,
        has_impl_plan=False,
        after=[],
        delivered_at=delivered_at,
    )


def test_todo_list_renders_active_with_default_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    snapshot: SnapshotAssertion,
) -> None:
    repo_root, worktree = _make_worktree(tmp_path)
    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(worktree))
    monkeypatch.chdir(worktree)
    service = SimpleNamespace(
        roadmap=SimpleNamespace(entries=MagicMock(return_value=[_sample_todo(_ACTIVE_SLUG, RoadmapStatus.READY)]))
    )

    with patch("teleclaude.cli.telec.handlers.todo.get_work_service", return_value=service) as get_service:
        todo._handle_todo_list([])

    get_service.assert_called_once_with(str(repo_root))
    service.roadmap.entries.assert_called_once_with(
        include_icebox=True,
        include_delivered=True,
        delivered_since=None,
    )
    assert capsys.readouterr().out == snapshot


def test_todo_list_renders_active_icebox_delivered_with_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    snapshot: SnapshotAssertion,
) -> None:
    _, worktree = _make_worktree(tmp_path)
    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(worktree))
    monkeypatch.chdir(worktree)
    service = SimpleNamespace(
        roadmap=SimpleNamespace(
            entries=MagicMock(
                return_value=[
                    _sample_todo(_ACTIVE_SLUG, RoadmapStatus.READY),
                    _sample_todo(_ICEBOX_SLUG, RoadmapStatus.ICEBOX),
                    _sample_todo(_DELIVERED_SLUG, RoadmapStatus.DELIVERED),
                ]
            )
        )
    )

    with patch("teleclaude.cli.telec.handlers.todo.get_work_service", return_value=service):
        todo._handle_todo_list(["--include-icebox", "--include-delivered"])

    assert capsys.readouterr().out == snapshot


def test_todo_list_since_parses_relative_and_iso() -> None:
    relative = todo._parse_todo_list_args(["--include-delivered", "--since", _SINCE_DAYS])
    absolute = todo._parse_todo_list_args(["--delivered-only", "--since", _SINCE_ISO])

    relative_cutoff = datetime.fromisoformat(relative["since_cutoff"])
    assert timedelta(days=6, hours=23) < datetime.now(UTC) - relative_cutoff < timedelta(days=7, hours=1)
    assert absolute["since_cutoff"] == datetime(2026, 5, 1, tzinfo=UTC).isoformat()


def test_todo_list_json_output_emits_valid_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, worktree = _make_worktree(tmp_path)
    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(worktree))
    monkeypatch.chdir(worktree)
    service = SimpleNamespace(
        roadmap=SimpleNamespace(entries=MagicMock(return_value=[_sample_todo(_ACTIVE_SLUG, RoadmapStatus.READY)]))
    )

    with patch("teleclaude.cli.telec.handlers.todo.get_work_service", return_value=service):
        todo._handle_todo_list(["--json"])

    assert json.loads(capsys.readouterr().out) == {
        "active": [{"slug": _ACTIVE_SLUG, "status": RoadmapStatus.READY, "description": _ACTIVE_SLUG}]
    }


def test_todo_list_json_empty_output_emits_empty_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, worktree = _make_worktree(tmp_path)
    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(worktree))
    monkeypatch.chdir(worktree)
    service = SimpleNamespace(roadmap=SimpleNamespace(entries=MagicMock(return_value=[])))

    with patch("teleclaude.cli.telec.handlers.todo.get_work_service", return_value=service):
        todo._handle_todo_list(["--json"])

    assert json.loads(capsys.readouterr().out) == {}


def test_todo_freeze_unfreeze_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(project))
    monkeypatch.chdir(project)
    database = _database(project)
    asyncio.run(database.initialize())
    try:
        asyncio.run(database.add_to_roadmap(_ACTIVE_SLUG))
        asyncio.run(database.write_state(_ACTIVE_SLUG, _TODO_STATE))

        todo._handle_todo_freeze([_ACTIVE_SLUG])
        assert _entry_status(database, _ACTIVE_SLUG)[0] == RoadmapStatus.ICEBOX

        todo._handle_todo_unfreeze([_ACTIVE_SLUG])
        assert _entry_status(database, _ACTIVE_SLUG)[0] == RoadmapStatus.ACTIVE
    finally:
        asyncio.run(database.close())


def test_todo_deliver_calls_cleanup_delivered_slug(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_called: list[tuple[Path, str, str]] = []
    repo_root, worktree = _make_worktree(tmp_path)
    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(worktree))
    monkeypatch.chdir(worktree)
    monkeypatch.setattr(
        todo,
        "_run_db",
        lambda project_root, slug, method, **kw: db_called.append((project_root, slug, method)) or True,
    )

    with patch("teleclaude.cli.telec.handlers.todo.cleanup_delivered_slug") as cleanup:
        todo._handle_todo_deliver([_ACTIVE_SLUG, "--commit", _COMMIT_HASH])

    assert db_called[0] == (repo_root, _ACTIVE_SLUG, "deliver")
    cleanup.assert_called_once_with(str(repo_root), _ACTIVE_SLUG)


def test_todo_deliver_marks_delivered_and_clears_ready_since(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(project))
    monkeypatch.chdir(project)
    database = _database(project)
    asyncio.run(database.initialize())
    try:
        asyncio.run(database.add_to_roadmap(_ACTIVE_SLUG, after=[_DEPENDENCY_SLUG]))
        asyncio.run(database.write_state(_ACTIVE_SLUG, _TODO_STATE))
        database.stamp_ready_since_if_null_sync(_ACTIVE_SLUG, _READY_SINCE)

        with patch("teleclaude.cli.telec.handlers.todo.cleanup_delivered_slug"):
            todo._handle_todo_deliver([_ACTIVE_SLUG, "--commit", _COMMIT_HASH])

        assert _entry_status(database, _ACTIVE_SLUG) == (RoadmapStatus.DELIVERED, None)
    finally:
        asyncio.run(database.close())
