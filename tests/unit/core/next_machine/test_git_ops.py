"""Characterization tests for git policy helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from git.exc import GitCommandError

from teleclaude.core.next_machine.git_ops import (
    _has_meaningful_diff,
    build_git_hook_env,
    compose_agent_guidance,
    get_stash_entries,
    has_build_commits_beyond_main,
    has_uncommitted_changes,
    review_surface_overlap_files,
)


def test_build_git_hook_env_moves_venv_bin_to_front_and_sets_virtual_env(tmp_path: Path) -> None:
    env = build_git_hook_env(str(tmp_path), {"PATH": "/usr/bin:/bin"})

    assert env["PATH"].split(":", maxsplit=1)[0] == str(tmp_path / ".venv" / "bin")
    assert env["VIRTUAL_ENV"] == str(tmp_path / ".venv")


def test_has_uncommitted_changes_ignores_orchestrator_paths(tmp_path: Path) -> None:
    worktree = tmp_path / "trees" / "slug-a"
    worktree.mkdir(parents=True)

    with (
        patch("teleclaude.core.next_machine.git_ops.Repo", return_value=SimpleNamespace()),
        patch(
            "teleclaude.core.next_machine.git_ops._dirty_paths",
            return_value=[".teleclaude/runtime.json"],
        ),
    ):
        dirty = has_uncommitted_changes(str(tmp_path), "slug-a")

    assert dirty is False


def test_has_uncommitted_changes_flags_unrelated_worktree_paths(tmp_path: Path) -> None:
    worktree = tmp_path / "trees" / "slug-b"
    worktree.mkdir(parents=True)

    with (
        patch("teleclaude.core.next_machine.git_ops.Repo", return_value=SimpleNamespace()),
        patch("teleclaude.core.next_machine.git_ops._dirty_paths", return_value=["src/app.py"]),
    ):
        dirty = has_uncommitted_changes(str(tmp_path), "slug-b")

    assert dirty is True


def test_get_stash_entries_returns_empty_on_git_command_error(tmp_path: Path) -> None:
    repo = SimpleNamespace(git=SimpleNamespace(stash=lambda *_args: (_ for _ in ()).throw(GitCommandError("stash", 1))))

    with patch("teleclaude.core.next_machine.git_ops.Repo", return_value=repo):
        entries = get_stash_entries(str(tmp_path))

    assert entries == []


def test_has_build_commits_beyond_main_propagates_git_command_error() -> None:
    repo = SimpleNamespace(
        git=SimpleNamespace(merge_base=lambda *_args: (_ for _ in ()).throw(GitCommandError("merge-base", 1)))
    )

    with patch("teleclaude.core.next_machine.git_ops.Repo", return_value=repo):
        with patch("teleclaude.core.next_machine.git_ops.logger.warning") as mock_warning:
            with pytest.raises(GitCommandError):
                has_build_commits_beyond_main("/repo")

    mock_warning.assert_called_once()


def test_has_meaningful_diff_filters_infrastructure_only_changes() -> None:
    mock_repo = MagicMock()
    mock_repo.git.log.return_value = ".teleclaude/run.json\n.teleclaude/todos.db\n"

    with patch("teleclaude.core.next_machine.git_ops.Repo", return_value=mock_repo):
        meaningful = _has_meaningful_diff("/repo", "base", "head")

    assert meaningful is False


def test_review_surface_overlap_files_returns_only_meaningful_overlap() -> None:
    mock_repo = MagicMock()
    mock_repo.git.log.return_value = "src/feature.py\n.teleclaude/todos.db\nsrc/other.py\n"
    mock_repo.git.diff.return_value = "src/feature.py\n.teleclaude/runtime.json\n"

    with patch("teleclaude.core.next_machine.git_ops.Repo", return_value=mock_repo):
        overlap = review_surface_overlap_files("/repo", "before", "after")

    assert overlap == ["src/feature.py"]


async def test_compose_agent_guidance_lists_enabled_agents_and_skips_unavailable() -> None:
    db = AsyncMock()
    db.get_agent_availability.side_effect = [
        None,
        {"status": "degraded", "reason": "slow quota"},
        {"status": "unavailable"},
    ]
    app_config = SimpleNamespace(
        agents={
            "alpha": SimpleNamespace(enabled=True),
            "beta": SimpleNamespace(enabled=True),
            "gamma": SimpleNamespace(enabled=True),
        }
    )
    agent_names = [
        SimpleNamespace(value="alpha"),
        SimpleNamespace(value="beta"),
        SimpleNamespace(value="gamma"),
    ]

    with (
        patch("teleclaude.core.next_machine.git_ops.app_config", app_config),
        patch("teleclaude.core.next_machine.git_ops.AgentName", agent_names),
    ):
        guidance = await compose_agent_guidance(db)

    assert "- ALPHA: available" in guidance
    assert "- BETA [DEGRADED: slow quota]" in guidance
    assert "- GAMMA" not in guidance
