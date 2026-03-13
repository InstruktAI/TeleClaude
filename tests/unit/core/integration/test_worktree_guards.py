"""Tests for _ensure_integration_worktree merge state guards.

Verifies that git reset --hard is skipped when MERGE_HEAD or SQUASH_MSG
exist in the worktree's git directory, and when _git_dir cannot be
resolved (fail-safe).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from teleclaude.core.integration.step_functions import _ensure_integration_worktree


def _mock_run_git_success(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:  # noqa: ARG001
    """Mock git that succeeds for all commands."""
    return 0, "", ""


# ---------------------------------------------------------------------------
# Merge state guards skip reset --hard
# ---------------------------------------------------------------------------


@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_run_git_success)
@patch("teleclaude.core.integration.step_functions._merge_head_exists", return_value=True)
def test_skips_reset_when_merge_head_exists(
    _mock_merge_head: Any, mock_git: MagicMock, tmp_path: Path
) -> None:
    """Active merge (MERGE_HEAD present) must skip fetch + reset."""
    wt_path = tmp_path / "trees" / "_integration"
    wt_path.mkdir(parents=True)

    path, err = _ensure_integration_worktree(str(tmp_path))
    assert err == ""
    assert path == wt_path

    for call in mock_git.call_args_list:
        args = call[0][0]
        assert args[:2] != ["fetch", "origin"], "fetch should not be called when MERGE_HEAD exists"
        assert args[:2] != ["reset", "--hard"], "reset --hard should not be called when MERGE_HEAD exists"


@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_run_git_success)
@patch("teleclaude.core.integration.step_functions._merge_head_exists", return_value=False)
@patch("teleclaude.core.integration.step_functions._git_dir")
def test_skips_reset_when_squash_msg_exists(
    mock_git_dir: MagicMock, _mock_merge_head: Any, mock_git: MagicMock, tmp_path: Path
) -> None:
    """In-progress squash merge (SQUASH_MSG present) must skip fetch + reset."""
    wt_path = tmp_path / "trees" / "_integration"
    wt_path.mkdir(parents=True)

    fake_git_dir = tmp_path / "fake_git_dir"
    fake_git_dir.mkdir()
    (fake_git_dir / "SQUASH_MSG").write_text("squash merge in progress")
    mock_git_dir.return_value = fake_git_dir

    path, err = _ensure_integration_worktree(str(tmp_path))
    assert err == ""
    assert path == wt_path

    for call in mock_git.call_args_list:
        args = call[0][0]
        assert args[:2] != ["reset", "--hard"], "reset --hard should not be called when SQUASH_MSG exists"


@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_run_git_success)
@patch("teleclaude.core.integration.step_functions._merge_head_exists", return_value=False)
@patch("teleclaude.core.integration.step_functions._git_dir", return_value=None)
def test_skips_reset_when_git_dir_unresolvable(
    _mock_git_dir: Any, _mock_merge_head: Any, mock_git: MagicMock, tmp_path: Path
) -> None:
    """When _git_dir returns None, skip reset (fail-safe: cannot determine state)."""
    wt_path = tmp_path / "trees" / "_integration"
    wt_path.mkdir(parents=True)

    path, err = _ensure_integration_worktree(str(tmp_path))
    assert err == ""
    assert path == wt_path

    for call in mock_git.call_args_list:
        args = call[0][0]
        assert args[:2] != ["reset", "--hard"], "reset --hard should not be called when git dir is unresolvable"


@patch("teleclaude.core.integration.step_functions._run_git", side_effect=_mock_run_git_success)
@patch("teleclaude.core.integration.step_functions._merge_head_exists", return_value=False)
@patch("teleclaude.core.integration.step_functions._git_dir")
def test_proceeds_with_reset_when_no_merge_state(
    mock_git_dir: MagicMock, _mock_merge_head: Any, mock_git: MagicMock, tmp_path: Path
) -> None:
    """When no merge state exists, fetch + reset --hard proceeds normally."""
    wt_path = tmp_path / "trees" / "_integration"
    wt_path.mkdir(parents=True)

    fake_git_dir = tmp_path / "fake_git_dir"
    fake_git_dir.mkdir()
    mock_git_dir.return_value = fake_git_dir

    path, err = _ensure_integration_worktree(str(tmp_path))
    assert err == ""
    assert path == wt_path

    git_commands = [call[0][0][:2] for call in mock_git.call_args_list]
    assert ["fetch", "origin"] in git_commands, "fetch should be called when no merge state"
    assert ["reset", "--hard"] in git_commands, "reset --hard should be called when no merge state"
