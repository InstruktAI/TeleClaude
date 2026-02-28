"""Regression tests for roadmap/bugs status parity."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.cli import telec


def test_bugs_list_uses_worktree_state_for_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """bugs list and roadmap list should agree on worktree-owned build status."""
    project_root = tmp_path
    slug = "fix-bug"

    todos_dir = project_root / "todos"
    todo_dir = todos_dir / slug
    todo_dir.mkdir(parents=True)
    (todos_dir / "roadmap.yaml").write_text(f"- slug: {slug}\n", encoding="utf-8")
    (todo_dir / "bug.md").write_text("# Bug\n", encoding="utf-8")
    (todo_dir / "state.yaml").write_text("build: pending\nreview: pending\n", encoding="utf-8")

    worktree_todo = project_root / "trees" / slug / "todos" / slug
    worktree_todo.mkdir(parents=True, exist_ok=True)
    (worktree_todo / "state.yaml").write_text("build: started\nreview: pending\n", encoding="utf-8")

    monkeypatch.chdir(project_root)

    telec._handle_roadmap(["list"])
    roadmap_output = capsys.readouterr().out
    assert "Build:started" in roadmap_output

    telec._handle_bugs(["list"])
    bugs_output = capsys.readouterr().out
    bug_lines = [line for line in bugs_output.splitlines() if slug in line]
    assert bug_lines
    assert any("building" in line for line in bug_lines)
