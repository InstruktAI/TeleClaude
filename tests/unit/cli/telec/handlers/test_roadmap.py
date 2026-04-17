"""Tests for telec roadmap handler worktree behavior."""
# pylint: disable=missing-function-docstring,protected-access

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
    }


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
    with patch("teleclaude.core.roadmap.assemble_roadmap_from_db", return_value=todos) as assemble:
        roadmap._handle_roadmap_show(["--json"])

    assemble.assert_called_once_with(
        str(repo_root),
        include_icebox=False,
        icebox_only=False,
        include_delivered=False,
        delivered_only=False,
    )
    assert json.loads(capsys.readouterr().out) == [{"slug": "sample", "status": "ready"}]


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

    with patch("teleclaude.core.next_machine.core.cleanup_delivered_slug") as cleanup:
        roadmap._handle_roadmap_deliver(["sample", "--commit", "abc123"])

    assert db_called[0] == (repo_root, "sample", "deliver")
    cleanup.assert_called_once_with(str(repo_root), "sample")
