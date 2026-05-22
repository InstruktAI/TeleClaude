"""Tests for the telec todo list verb (handlers/todo_list.py)."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.api_models import TodoDTO
from teleclaude.constants import RoadmapStatus

todo_list = importlib.import_module("teleclaude.cli.telec.handlers.todo_list")

_ACTIVE_SLUG = "active-item"
_ICEBOX_SLUG = "icebox-item"
_DELIVERED_SLUG = "delivered-item"
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

    with patch("teleclaude.cli.telec.handlers.todo_list.get_work_service", return_value=service) as get_service:
        todo_list._handle_todo_list([])

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

    with patch("teleclaude.cli.telec.handlers.todo_list.get_work_service", return_value=service):
        todo_list._handle_todo_list(["--include-icebox", "--include-delivered"])

    assert capsys.readouterr().out == snapshot


def test_todo_list_since_parses_relative_and_iso() -> None:
    relative = todo_list._parse_todo_list_args(["--include-delivered", "--since", _SINCE_DAYS])
    absolute = todo_list._parse_todo_list_args(["--delivered-only", "--since", _SINCE_ISO])

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

    with patch("teleclaude.cli.telec.handlers.todo_list.get_work_service", return_value=service):
        todo_list._handle_todo_list(["--json"])

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

    with patch("teleclaude.cli.telec.handlers.todo_list.get_work_service", return_value=service):
        todo_list._handle_todo_list(["--json"])

    assert json.loads(capsys.readouterr().out) == {}
