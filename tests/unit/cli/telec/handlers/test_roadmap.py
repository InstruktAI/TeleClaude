"""Tests for telec roadmap handler worktree behavior."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

roadmap = importlib.import_module("teleclaude.cli.telec.handlers.roadmap")


def _make_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "main"
    worktree = tmp_path / "trees" / "sample"
    gitdir = repo_root / ".git" / "worktrees" / "sample"
    gitdir.mkdir(parents=True)
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    return repo_root, worktree


def test_parse_roadmap_show_args_sets_requested_flags() -> None:
    parsed = roadmap._parse_roadmap_show_args(["--include-icebox", "--delivered-only", "--json"])

    assert parsed == {
        "include_icebox": True,
        "icebox_only": False,
        "include_delivered": False,
        "delivered_only": True,
        "json_output": True,
        "since_cutoff": "",
    }


def test_parse_roadmap_show_args_parses_since_duration() -> None:
    parsed = roadmap._parse_roadmap_show_args(["--include-delivered", "--since", "7d"])

    assert parsed["include_delivered"] is True
    assert parsed["since_cutoff"]  # non-empty ISO cutoff string
    # cutoff is a parseable ISO timestamp roughly 7 days in the past
    cutoff = datetime.fromisoformat(parsed["since_cutoff"])
    age = datetime.now(UTC) - cutoff
    assert timedelta(days=6, hours=23) < age < timedelta(days=7, hours=1)


def test_parse_roadmap_show_args_rejects_bad_since() -> None:
    with pytest.raises(SystemExit):
        roadmap._parse_roadmap_show_args(["--since", "not-a-date"])
    with pytest.raises(SystemExit):
        roadmap._parse_roadmap_show_args(["--since"])


def test_handle_roadmap_show_prints_json_when_requested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    todos = [
        SimpleNamespace(
            slug="sample",
            status="ready",
            description=None,
            after=[],
            group=None,
            delivered_at=None,
        )
    ]

    repo_root, worktree = _make_worktree(tmp_path)
    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(worktree))
    monkeypatch.chdir(worktree)
    service = SimpleNamespace(roadmap=SimpleNamespace(entries=MagicMock(return_value=todos)))
    with patch("teleclaude.cli.telec.handlers.roadmap.get_work_service", return_value=service) as get_service:
        roadmap._handle_roadmap_show(["--json"])

    get_service.assert_called_once_with(str(repo_root))
    service.roadmap.entries.assert_called_once_with(
        include_icebox=True,
        include_delivered=True,
        delivered_since=None,
    )
    assert json.loads(capsys.readouterr().out) == {"active": [{"slug": "sample", "status": "ready"}]}


def test_handle_roadmap_add_forwards_parsed_options(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_called: list[tuple[Path, str, str]] = []
    repo_root, worktree = _make_worktree(tmp_path)
    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(worktree))
    monkeypatch.chdir(worktree)
    with patch(
        "teleclaude.cli.telec.handlers.roadmap._run_db",
        side_effect=lambda project_root, slug, method, **kw: db_called.append((project_root, slug, method)) or True,
    ):
        roadmap._handle_roadmap_add(
            ["sample", "--group", "core", "--after", "dep-a,dep-b", "--description", "Demo", "--before", "other"]
        )

    assert db_called[0] == (repo_root, "sample", "add_to_roadmap")


def test_handle_roadmap_deliver_calls_db_and_cleanup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_called: list[tuple[Path, str, str]] = []
    repo_root, worktree = _make_worktree(tmp_path)
    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(worktree))
    monkeypatch.chdir(worktree)
    monkeypatch.setattr(
        roadmap,
        "_run_db",
        lambda project_root, slug, method, **kw: db_called.append((project_root, slug, method)) or True,
    )

    with patch("teleclaude.cli.telec.handlers.roadmap.cleanup_delivered_slug") as cleanup:
        roadmap._handle_roadmap_deliver(["sample", "--commit", "abc123"])

    assert db_called[0] == (repo_root, "sample", "deliver")
    cleanup.assert_called_once_with(str(repo_root), "sample")
