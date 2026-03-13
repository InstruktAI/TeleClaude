"""Reproduction test for delivery bookkeeping divergence bug.

Bug: bookkeeping commits (roadmap delivery, todo cleanup) were created on repo
root main and pushed separately from the squash merge commit, causing divergence
when repo root had local commits from other agents.

Fix: bookkeeping runs in the integration worktree so everything pushes atomically
via a single 'git push origin HEAD:main'. Repo root pull failure is non-fatal.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from teleclaude.core.integration.checkpoint import (
    IntegrationCheckpoint,
    IntegrationPhase,
    _write_checkpoint,
)
from teleclaude.core.integration.step_functions import (
    _step_delivery_bookkeeping,
    _step_push_succeeded,
)


def _make_checkpoint(
    tmp_path: Path, *, phase: str = IntegrationPhase.DELIVERY_BOOKKEEPING.value
) -> tuple[IntegrationCheckpoint, Path]:
    cp = IntegrationCheckpoint(
        phase=phase,
        candidate_slug="my-feature",
        candidate_branch="my-feature",
        candidate_sha="a" * 40,
        lease_token=None,
        items_processed=0,
        items_blocked=0,
        started_at="2026-01-01T00:00:00+00:00",
        last_updated_at="2026-01-01T00:00:00+00:00",
        error_context=None,
        pre_merge_head="b" * 40,
    )
    cp_path = tmp_path / "integrate-state.json"
    _write_checkpoint(cp_path, cp)
    return cp, cp_path


def test_bookkeeping_runs_in_integration_worktree_not_repo_root(tmp_path: Path) -> None:
    """Regression: bookkeeping (roadmap delivery, todo removal) must run in the
    integration worktree so all commits push atomically to origin/main.

    Old behavior: these ran on repo root, then a separate push was attempted —
    causing divergence when repo root had local commits from other agents.
    """
    slug = "my-feature"
    wt = tmp_path / "trees" / "_integration"
    wt.mkdir(parents=True, exist_ok=True)
    # Simulate todo dir in worktree so git rm path is exercised
    (wt / "todos" / slug).mkdir(parents=True, exist_ok=True)

    cp, cp_path = _make_checkpoint(tmp_path)

    git_calls: list[tuple[list[str], str]] = []

    def mock_run_git(
        args: list[str], *, cwd: str, timeout: float = 30
    ) -> tuple[int, str, str]:
        git_calls.append((list(args), cwd))
        if args[:2] == ["diff", "--cached"]:
            return 1, "", ""  # staged changes exist → trigger commit
        if args[0] == "push":
            return 0, "HEAD pushed", ""
        if args[:2] == ["rev-parse", "HEAD"]:
            return 0, "c" * 40 + "\n", ""
        return 0, "", ""

    deliver_called_with: list[str] = []
    clean_dep_called_with: list[str] = []

    def mock_deliver(cwd: str, slug: str) -> bool:
        deliver_called_with.append(cwd)
        return True

    def mock_clean_dep(cwd: str, slug: str) -> None:
        clean_dep_called_with.append(cwd)

    with (
        patch(
            "teleclaude.core.integration.step_functions._run_git",
            side_effect=mock_run_git,
        ),
        patch(
            "teleclaude.core.next_machine.core.deliver_to_delivered",
            side_effect=mock_deliver,
        ),
        patch(
            "teleclaude.core.next_machine.icebox.clean_dependency_references",
            side_effect=mock_clean_dep,
        ),
        patch("teleclaude.core.integration.step_functions._mirror_integration_phase"),
    ):
        ok, _msg = _step_delivery_bookkeeping(
            checkpoint=cp,
            checkpoint_path=cp_path,
            cwd=str(tmp_path),
        )

    wt_str = str(wt)

    # Fix verified: bookkeeping called with integration worktree, not repo root
    assert deliver_called_with == [wt_str], (
        f"deliver_to_delivered must use integration worktree; got {deliver_called_with}"
    )
    assert clean_dep_called_with == [wt_str], (
        f"clean_dependency_references must use integration worktree; got {clean_dep_called_with}"
    )

    # All git operations targeting main must originate from integration worktree
    push_calls = [(args, cwd) for args, cwd in git_calls if args[0] == "push"]
    assert len(push_calls) == 1, f"expected exactly one push, got {len(push_calls)}"
    push_args, push_cwd = push_calls[0]
    assert push_cwd == wt_str, f"push must use integration worktree; got {push_cwd}"
    assert push_args == ["push", "origin", "HEAD:main"], f"unexpected push args: {push_args}"

    # No git operations must target repo root for bookkeeping or push
    repo_root_git_ops = [
        (args, cwd)
        for args, cwd in git_calls
        if cwd == str(tmp_path) and args[0] in ("commit", "push", "rm")
    ]
    assert repo_root_git_ops == [], (
        f"bookkeeping git ops must not run on repo root; found: {repo_root_git_ops}"
    )

    assert ok is True
    assert cp.phase == IntegrationPhase.PUSH_SUCCEEDED.value


def test_repo_root_pull_failure_is_nonfatal(tmp_path: Path) -> None:
    """When repo root has local commits (non-fast-forwardable), pull --ff-only
    fails. This must be non-fatal because bookkeeping was already committed and
    pushed from the integration worktree atomically.
    """
    cp, cp_path = _make_checkpoint(tmp_path, phase=IntegrationPhase.PUSH_SUCCEEDED.value)

    pull_attempted = False

    def mock_run_git(
        args: list[str], *, cwd: str, timeout: float = 30
    ) -> tuple[int, str, str]:
        nonlocal pull_attempted
        if args[:3] == ["pull", "--ff-only", "origin"]:
            # Simulate repo root divergence — cannot fast-forward
            pull_attempted = True
            return 1, "", "fatal: not possible to fast-forward, aborting."
        if args[:2] == ["rev-parse", "HEAD"]:
            return 0, "d" * 40 + "\n", ""
        return 0, "", ""

    queue = MagicMock()

    with (
        patch(
            "teleclaude.core.integration.step_functions._run_git",
            side_effect=mock_run_git,
        ),
        patch("teleclaude.core.next_machine.core.cleanup_delivered_slug"),
        patch("teleclaude.core.integration.step_functions._mirror_integration_phase"),
        patch("teleclaude.core.integration.step_functions._emit_lifecycle_event"),
    ):
        ok, _msg = _step_push_succeeded(
            checkpoint=cp,
            checkpoint_path=cp_path,
            queue=queue,
            cwd=str(tmp_path),
        )

    assert pull_attempted, "pull --ff-only must be attempted on repo root"
    # Non-fatal: step proceeds through cleanup despite pull failure
    assert ok is True, "repo root pull failure must not abort the integration flow"
    assert cp.phase == IntegrationPhase.CANDIDATE_DELIVERED.value
