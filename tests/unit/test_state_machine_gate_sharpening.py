"""Unit tests for state-machine-gate-sharpening fixes.

Covers:
- _has_meaningful_diff: filtering, merge commit exclusion, subprocess errors
- Stale baseline guard integration (review approval invalidation)
- Gate failure with review_round > 0 (build preserved)
- Gate failure with review_round == 0 (build reset to started)
- _count_test_failures: parsing pytest summary
- run_build_gates retry path for low-count flaky failures
- run_build_gates no-retry for high-count failures
"""

import asyncio
from contextlib import ExitStack
import os
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core.db import Db
from teleclaude.core.next_machine import next_work
from teleclaude.core.next_machine.core import (
    _count_test_failures,
    _has_meaningful_diff,
    run_build_gates,
)


# ---------------------------------------------------------------------------
# _count_test_failures
# ---------------------------------------------------------------------------


def test_count_test_failures_parses_N_failed() -> None:
    output = "5 failed, 3 passed, 1 warning in 12.3s"
    assert _count_test_failures(output) == 5


def test_count_test_failures_single() -> None:
    output = "1 failed in 0.5s"
    assert _count_test_failures(output) == 1


def test_count_test_failures_no_match_returns_zero() -> None:
    output = "all tests passed"
    assert _count_test_failures(output) == 0


def test_count_test_failures_empty_string() -> None:
    assert _count_test_failures("") == 0


def test_count_test_failures_partial_match() -> None:
    output = "collected 10 items\n2 failed\n"
    assert _count_test_failures(output) == 2


# ---------------------------------------------------------------------------
# _has_meaningful_diff
# ---------------------------------------------------------------------------


def _make_log_run(file_lines: list[str]) -> MagicMock:
    """Build a CompletedProcess mock for git log --no-merges --name-only output.

    git log --pretty=format: produces empty lines between commits; the function
    filters those out via `f.strip()`.
    """
    result = MagicMock()
    result.stdout = "\n".join(file_lines) + ("\n" if file_lines else "")
    result.returncode = 0
    return result


def test_has_meaningful_diff_real_file() -> None:
    """Returns True when a non-infrastructure file changed in a non-merge commit."""
    log_run = _make_log_run(["teleclaude/core/next_machine/core.py"])

    with patch("subprocess.run", return_value=log_run):
        assert _has_meaningful_diff("/repo", "abc", "def") is True


def test_has_meaningful_diff_only_todos() -> None:
    """Returns False when only todos/ files changed."""
    log_run = _make_log_run(["todos/some-slug/state.yaml", "todos/roadmap.yaml"])

    with patch("subprocess.run", return_value=log_run):
        assert _has_meaningful_diff("/repo", "abc", "def") is False


def test_has_meaningful_diff_only_teleclaude() -> None:
    """Returns False when only .teleclaude/ files changed."""
    log_run = _make_log_run([".teleclaude/worktree-prep-state.json"])

    with patch("subprocess.run", return_value=log_run):
        assert _has_meaningful_diff("/repo", "abc", "def") is False


def test_has_meaningful_diff_mixed_infra_and_real() -> None:
    """Returns True when infra + real files both changed."""
    log_run = _make_log_run(["todos/slug/state.yaml", "teleclaude/core/foo.py"])

    with patch("subprocess.run", return_value=log_run):
        assert _has_meaningful_diff("/repo", "abc", "def") is True


def test_has_meaningful_diff_merge_commit_only_real_file_excluded() -> None:
    """File introduced solely by a merge commit does not appear in --no-merges log."""
    # The --no-merges log returns nothing: only the merge commit touched this file.
    log_run = _make_log_run([])

    with patch("subprocess.run", return_value=log_run):
        assert _has_meaningful_diff("/repo", "abc", "def") is False


def test_has_meaningful_diff_file_in_merge_and_real_commit_included() -> None:
    """File touched by BOTH a merge commit and a regular commit is correctly included.

    This is the C-1 regression: the old subtraction algorithm would remove the file
    because the merge commit touched it. The new --no-merges approach includes it
    because the regular commit also changed it.
    """
    log_run = _make_log_run(["teleclaude/core/foo.py"])

    with patch("subprocess.run", return_value=log_run):
        assert _has_meaningful_diff("/repo", "abc", "def") is True


def test_has_meaningful_diff_merge_removes_only_some() -> None:
    """When two real files change but one is only from a merge, the other remains."""
    # --no-merges log only shows bar.py (the regular commit file)
    log_run = _make_log_run(["teleclaude/core/bar.py"])

    with patch("subprocess.run", return_value=log_run):
        assert _has_meaningful_diff("/repo", "abc", "def") is True


def test_has_meaningful_diff_no_changes() -> None:
    """Returns False when no non-merge commits touched any files."""
    log_run = _make_log_run([])

    with patch("subprocess.run", return_value=log_run):
        assert _has_meaningful_diff("/repo", "abc", "def") is False


def test_has_meaningful_diff_subprocess_error_returns_true() -> None:
    """Returns True (fail-safe) on subprocess.CalledProcessError."""
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")):
        assert _has_meaningful_diff("/repo", "abc", "def") is True


def test_has_meaningful_diff_oserror_returns_true() -> None:
    """Returns True (fail-safe) on OSError."""
    with patch("subprocess.run", side_effect=OSError("git not found")):
        assert _has_meaningful_diff("/repo", "abc", "def") is True


# ---------------------------------------------------------------------------
# Stale baseline guard integration
# ---------------------------------------------------------------------------


def _make_ensure_mock() -> AsyncMock:
    """Create an AsyncMock for ensure_worktree_with_policy_async."""
    result = MagicMock()
    result.created = False
    result.prepared = False
    result.prep_reason = "skip"
    mock = AsyncMock(return_value=result)
    return mock


def _make_lock_mock() -> AsyncMock:
    """Create an AsyncMock for _get_slug_single_flight_lock returning a real asyncio.Lock."""
    return AsyncMock(return_value=asyncio.Lock())


def _apply_base_patches(stack: ExitStack, extra: dict | None = None) -> dict:
    """Enter common patches via ExitStack. Returns dict of named mocks."""
    ns = "teleclaude.core.next_machine.core"
    mocks: dict = {}
    stack.enter_context(patch(f"{ns}.load_roadmap_deps", return_value={}))
    stack.enter_context(patch(f"{ns}.is_bug_todo", return_value=False))
    stack.enter_context(patch(f"{ns}.slug_in_roadmap", return_value=True))
    stack.enter_context(patch(f"{ns}.get_item_phase", return_value="in_progress"))
    stack.enter_context(patch(f"{ns}.check_dependencies_satisfied", return_value=True))
    stack.enter_context(patch(f"{ns}.check_file_exists", return_value=True))
    stack.enter_context(patch(f"{ns}.get_stash_entries", return_value=[]))
    stack.enter_context(patch(f"{ns}._get_slug_single_flight_lock", new=_make_lock_mock()))
    stack.enter_context(patch(f"{ns}.ensure_worktree_with_policy_async", new=_make_ensure_mock()))
    stack.enter_context(patch(f"{ns}.sync_main_to_worktree", return_value=0))
    stack.enter_context(patch(f"{ns}.has_uncommitted_changes", return_value=False))
    for key, kwargs in (extra or {}).items():
        mock = stack.enter_context(patch(f"{ns}.{key}", **kwargs))
        mocks[key] = mock
    return mocks


@pytest.mark.asyncio
async def test_next_work_review_approved_infra_only_diff_holds() -> None:
    """Review approval is preserved when only infrastructure files changed since baseline."""
    db = MagicMock(spec=Db)
    cwd = "/repo"
    slug = "my-slug"
    state = {
        "build": "complete",
        "review": "approved",
        "review_baseline_commit": "baseline_sha",
        "review_round": 1,
    }

    with ExitStack() as stack:
        mocks = _apply_base_patches(
            stack,
            {
                "read_phase_state": dict(return_value=state),
                "_get_head_commit": dict(return_value="head_sha"),
                "_has_meaningful_diff": dict(return_value=False),
                "mark_phase": dict(),
                "has_pending_deferrals": dict(return_value=False),
            },
        )
        stack.enter_context(
            patch("teleclaude.core.next_machine.core.compose_agent_guidance", new=AsyncMock(return_value="GUIDANCE"))
        )
        stack.enter_context(
            patch("teleclaude.core.next_machine.core.emit_review_approved", new=AsyncMock())
        )
        result = await next_work(db, slug=slug, cwd=cwd, caller_session_id="sess-123")

    mock_mark = mocks["mark_phase"]
    reset_calls = [c for c in mock_mark.call_args_list if "review" in str(c) and "pending" in str(c)]
    assert reset_calls == [], f"Review should not have been reset; got: {reset_calls}"
    assert "next-finalize" in result


@pytest.mark.asyncio
async def test_next_work_review_approved_real_diff_invalidates() -> None:
    """Review approval is invalidated when real (non-infra) files changed since baseline."""
    db = MagicMock(spec=Db)
    cwd = "/repo"
    slug = "my-slug"
    state = {
        "build": "complete",
        "review": "approved",
        "review_baseline_commit": "baseline_sha",
        "review_round": 1,
    }

    with ExitStack() as stack:
        mocks = _apply_base_patches(
            stack,
            {
                "read_phase_state": dict(return_value=state),
                "_get_head_commit": dict(return_value="head_sha"),
                "_has_meaningful_diff": dict(return_value=True),
                "mark_phase": dict(),
                "run_build_gates": dict(return_value=(True, "GATE PASSED: make test")),
                "verify_artifacts": dict(return_value=(True, "ARTIFACT CHECKS PASSED")),
                "has_pending_deferrals": dict(return_value=False),
                "_is_review_round_limit_reached": dict(return_value=(False, 1, 3)),
            },
        )
        stack.enter_context(
            patch("teleclaude.core.next_machine.core.compose_agent_guidance", new=AsyncMock(return_value="GUIDANCE"))
        )
        result = await next_work(db, slug=slug, cwd=cwd)

    mock_mark = mocks["mark_phase"]
    reset_calls = [c for c in mock_mark.call_args_list if "pending" in str(c)]
    assert reset_calls, "Review should have been invalidated (reset to pending)"
    assert "next-review" in result


# ---------------------------------------------------------------------------
# Gate failure: review_round behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_work_gate_failure_review_round_zero_resets_build() -> None:
    """When gates fail and review_round == 0, build is reset to started."""
    db = MagicMock(spec=Db)
    cwd = "/repo"
    slug = "my-slug"
    state = {"build": "complete", "review": "pending", "review_round": 0}

    with ExitStack() as stack:
        mocks = _apply_base_patches(
            stack,
            {
                "read_phase_state": dict(return_value=state),
                "run_build_gates": dict(return_value=(False, "GATE FAILED: make test")),
                "mark_phase": dict(),
            },
        )
        result = await next_work(db, slug=slug, cwd=cwd)

    mock_mark = mocks["mark_phase"]
    build_started_calls = [c for c in mock_mark.call_args_list if "started" in str(c) and "build" in str(c)]
    assert build_started_calls, f"Expected build reset to started; got: {mock_mark.call_args_list}"
    assert "BUILD GATES FAILED" in result


@pytest.mark.asyncio
async def test_next_work_gate_failure_review_round_gt_zero_keeps_build_complete() -> None:
    """When gates fail and review_round > 0, build status stays complete."""
    db = MagicMock(spec=Db)
    cwd = "/repo"
    slug = "my-slug"
    state = {"build": "complete", "review": "pending", "review_round": 1}

    with ExitStack() as stack:
        mocks = _apply_base_patches(
            stack,
            {
                "read_phase_state": dict(return_value=state),
                "run_build_gates": dict(return_value=(False, "GATE FAILED: make test")),
                "mark_phase": dict(),
            },
        )
        result = await next_work(db, slug=slug, cwd=cwd)

    mock_mark = mocks["mark_phase"]
    build_started_calls = [c for c in mock_mark.call_args_list if "started" in str(c) and "build" in str(c)]
    assert build_started_calls == [], f"Build should NOT be reset; got: {mock_mark.call_args_list}"
    assert "BUILD GATES FAILED" in result


# ---------------------------------------------------------------------------
# run_build_gates: retry path
# ---------------------------------------------------------------------------


def test_run_build_gates_retry_on_one_failure_passes() -> None:
    """When make test fails with 1 failure, retry with pytest --lf; if retry passes, gate passes."""
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stdout = "1 failed, 10 passed in 5.0s"
    fail_result.stderr = ""

    retry_result = MagicMock()
    retry_result.returncode = 0
    retry_result.stdout = "10 passed in 1.0s"

    with (
        patch("subprocess.run", side_effect=[fail_result, retry_result]),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=True),
    ):
        passed, output = run_build_gates("/worktree", "my-slug")

    assert passed is True
    assert "retry passed after 1 flaky failure(s)" in output


def test_run_build_gates_retry_on_two_failures_passes() -> None:
    """When make test fails with 2 failures, retry with pytest --lf; if retry passes, gate passes."""
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stdout = "2 failed, 8 passed in 4.0s"
    fail_result.stderr = ""

    retry_result = MagicMock()
    retry_result.returncode = 0
    retry_result.stdout = "8 passed in 1.0s"

    with (
        patch("subprocess.run", side_effect=[fail_result, retry_result]),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=True),
    ):
        passed, output = run_build_gates("/worktree", "my-slug")

    assert passed is True
    assert "retry passed after 2 flaky failure(s)" in output


def test_run_build_gates_retry_fails_gate_fails_combined_output() -> None:
    """When retry also fails, gate fails with combined output from both runs."""
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stdout = "1 failed in 3.0s"
    fail_result.stderr = ""

    retry_result = MagicMock()
    retry_result.returncode = 1
    retry_result.stdout = "still failing"

    with (
        patch("subprocess.run", side_effect=[fail_result, retry_result]),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=True),
    ):
        passed, output = run_build_gates("/worktree", "my-slug")

    assert passed is False
    assert "GATE FAILED" in output
    assert "RETRY ALSO FAILED" in output
    assert "still failing" in output


def test_run_build_gates_no_retry_when_three_failures() -> None:
    """When make test fails with 3 failures, no retry is attempted."""
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stdout = "3 failed, 7 passed in 6.0s"
    fail_result.stderr = ""

    with (
        patch("subprocess.run", return_value=fail_result) as mock_run,
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=True),
    ):
        passed, output = run_build_gates("/worktree", "my-slug")

    assert passed is False
    # subprocess.run should have been called exactly once (make test), no retry
    assert mock_run.call_count == 1
    assert "GATE FAILED" in output
    assert "RETRY" not in output


def test_run_build_gates_no_retry_when_unparseable_failure_count() -> None:
    """When pytest output has no failure count, no retry is attempted."""
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stdout = "ERROR: collection error"
    fail_result.stderr = ""

    with (
        patch("subprocess.run", return_value=fail_result) as mock_run,
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=True),
    ):
        passed, _output = run_build_gates("/worktree", "my-slug")

    assert passed is False
    assert mock_run.call_count == 1


def test_run_build_gates_retry_timeout_fails_gate() -> None:
    """When make test fails with 1 failure but the retry subprocess raises TimeoutExpired, gate fails."""
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stdout = "1 failed in 3.0s"
    fail_result.stderr = ""

    with (
        patch(
            "subprocess.run",
            side_effect=[fail_result, subprocess.TimeoutExpired(cmd="pytest", timeout=120)],
        ),
        patch("teleclaude.core.next_machine.core.check_file_exists", return_value=True),
    ):
        passed, output = run_build_gates("/worktree", "my-slug")

    assert passed is False
    assert "RETRY ERROR" in output


# ---------------------------------------------------------------------------
# Artifact verification failure: review_round behavior (I-5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_work_artifact_failure_review_round_zero_resets_build() -> None:
    """When artifact verification fails and review_round == 0, build is reset to started."""
    db = MagicMock(spec=Db)
    cwd = "/repo"
    slug = "my-slug"
    state = {"build": "complete", "review": "pending", "review_round": 0}

    with ExitStack() as stack:
        mocks = _apply_base_patches(
            stack,
            {
                "read_phase_state": dict(return_value=state),
                "run_build_gates": dict(return_value=(True, "GATE PASSED: make test")),
                "verify_artifacts": dict(return_value=(False, "ARTIFACT CHECKS FAILED")),
                "mark_phase": dict(),
            },
        )
        result = await next_work(db, slug=slug, cwd=cwd)

    mock_mark = mocks["mark_phase"]
    build_started_calls = [c for c in mock_mark.call_args_list if "started" in str(c) and "build" in str(c)]
    assert build_started_calls, f"Expected build reset to started; got: {mock_mark.call_args_list}"
    assert "BUILD GATES FAILED" in result


@pytest.mark.asyncio
async def test_next_work_artifact_failure_review_round_gt_zero_keeps_build_complete() -> None:
    """When artifact verification fails and review_round > 0, build stays complete."""
    db = MagicMock(spec=Db)
    cwd = "/repo"
    slug = "my-slug"
    state = {"build": "complete", "review": "pending", "review_round": 1}

    with ExitStack() as stack:
        mocks = _apply_base_patches(
            stack,
            {
                "read_phase_state": dict(return_value=state),
                "run_build_gates": dict(return_value=(True, "GATE PASSED: make test")),
                "verify_artifacts": dict(return_value=(False, "ARTIFACT CHECKS FAILED")),
                "mark_phase": dict(),
            },
        )
        result = await next_work(db, slug=slug, cwd=cwd)

    mock_mark = mocks["mark_phase"]
    build_started_calls = [c for c in mock_mark.call_args_list if "started" in str(c) and "build" in str(c)]
    assert build_started_calls == [], f"Build should NOT be reset; got: {mock_mark.call_args_list}"
    assert "BUILD GATES FAILED" in result
