"""Shared fixtures for next_machine tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.core.next_machine.worktrees import EnsureWorktreeResult


@pytest.fixture(autouse=True)
def _mock_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests use tmp_path (not a git repo) — stub out worktree creation."""

    async def _noop_ensure(*_args: object, **_kwargs: object) -> EnsureWorktreeResult:
        return EnsureWorktreeResult(created=False, prepared=False, prep_reason="test-stub")

    monkeypatch.setattr("teleclaude.core.next_machine.work.ensure_worktree_with_policy_async", _noop_ensure)


@pytest.fixture(autouse=True)
def _pin_commands_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin COMMANDS_DIR to a portable canonical path so snapshot output is reproducible.

    COMMANDS_DIR normally resolves under a per-pytest tmp directory, which
    makes any rendered output that embeds the path unstable across runs.
    The pinned placeholder is portable across users and machines.
    """
    monkeypatch.setattr(
        "teleclaude.core.next_machine.output_formatting.COMMANDS_DIR",
        Path("/test-commands"),
    )
