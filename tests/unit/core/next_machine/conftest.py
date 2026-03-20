"""Shared fixtures for next_machine tests."""

from __future__ import annotations

import pytest

from teleclaude.core.next_machine.worktrees import EnsureWorktreeResult


@pytest.fixture(autouse=True)
def _mock_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests use tmp_path (not a git repo) — stub out worktree creation."""

    async def _noop_ensure(*_args: object, **_kwargs: object) -> EnsureWorktreeResult:
        return EnsureWorktreeResult(created=False, prepared=False, prep_reason="test-stub")

    monkeypatch.setattr(
        "teleclaude.core.next_machine.prepare_steps.ensure_worktree_with_policy_async",
        _noop_ensure,
    )
