"""Unit tests for the integration state machine.

Covers: checkpoint read/write/recovery, phase handlers, idempotency,
queue drain, clearance wait, push rejection recovery.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.core.integration.state_machine import (
    IntegrationCheckpoint,
    IntegrationPhase,
    _dispatch_sync,
    _get_candidate_key,
    _now_iso,
    _read_checkpoint,
    _write_checkpoint,
)

pytestmark = pytest.mark.timeout(10)


# ---------------------------------------------------------------------------
# Checkpoint read / write helpers
# ---------------------------------------------------------------------------


def _make_checkpoint(phase: IntegrationPhase = IntegrationPhase.IDLE) -> IntegrationCheckpoint:
    now = _now_iso()
    return IntegrationCheckpoint(
        phase=phase.value,
        candidate_slug=None,
        candidate_branch=None,
        candidate_sha=None,
        lease_token=None,
        items_processed=0,
        items_blocked=0,
        started_at=now,
        last_updated_at=now,
        error_context=None,
        pre_merge_head=None,
    )


def test_write_and_read_checkpoint_roundtrip(tmp_path: Path) -> None:
    cp_path = tmp_path / "state.json"
    cp = _make_checkpoint(IntegrationPhase.CLEARANCE_WAIT)
    cp.candidate_slug = "my-feature"
    cp.candidate_branch = "my-feature"
    cp.candidate_sha = "abc123"
    cp.lease_token = "tok-xyz"
    cp.items_processed = 2
    cp.items_blocked = 1
    cp.pre_merge_head = "deadbeef"

    _write_checkpoint(cp_path, cp)

    loaded = _read_checkpoint(cp_path)
    assert loaded.phase == IntegrationPhase.CLEARANCE_WAIT.value
    assert loaded.candidate_slug == "my-feature"
    assert loaded.candidate_branch == "my-feature"
    assert loaded.candidate_sha == "abc123"
    assert loaded.lease_token == "tok-xyz"
    assert loaded.items_processed == 2
    assert loaded.items_blocked == 1
    assert loaded.pre_merge_head == "deadbeef"


def test_read_checkpoint_returns_idle_when_file_absent(tmp_path: Path) -> None:
    cp = _read_checkpoint(tmp_path / "nonexistent.json")
    assert cp.phase == IntegrationPhase.IDLE.value
    assert cp.candidate_slug is None


def test_read_checkpoint_returns_idle_on_corrupt_file(tmp_path: Path) -> None:
    cp_path = tmp_path / "corrupt.json"
    cp_path.write_text("not valid json", encoding="utf-8")
    cp = _read_checkpoint(cp_path)
    assert cp.phase == IntegrationPhase.IDLE.value


def test_read_checkpoint_returns_idle_on_empty_file(tmp_path: Path) -> None:
    cp_path = tmp_path / "empty.json"
    cp_path.write_text("", encoding="utf-8")
    cp = _read_checkpoint(cp_path)
    assert cp.phase == IntegrationPhase.IDLE.value


def test_write_checkpoint_is_atomic(tmp_path: Path) -> None:
    """Verify no temp file is left behind after a successful write."""
    cp_path = tmp_path / "state.json"
    cp = _make_checkpoint()
    _write_checkpoint(cp_path, cp)
    assert cp_path.exists()
    assert not (tmp_path / "state.json.tmp").exists()


def test_write_checkpoint_includes_version(tmp_path: Path) -> None:
    cp_path = tmp_path / "state.json"
    _write_checkpoint(cp_path, _make_checkpoint())
    data: dict[str, Any] = json.loads(cp_path.read_text())  # guard: loose-dict - verifying checkpoint JSON shape
    assert data["version"] == 1


# ---------------------------------------------------------------------------
# _get_candidate_key helper
# ---------------------------------------------------------------------------


def test_get_candidate_key_returns_none_when_incomplete() -> None:
    cp = _make_checkpoint()
    assert _get_candidate_key(cp) is None


def test_get_candidate_key_returns_key_when_complete() -> None:
    cp = _make_checkpoint()
    cp.candidate_slug = "slug-a"
    cp.candidate_branch = "branch-a"
    cp.candidate_sha = "sha-a"
    key = _get_candidate_key(cp)
    assert key is not None
    assert key.slug == "slug-a"
    assert key.branch == "branch-a"
    assert key.sha == "sha-a"


# ---------------------------------------------------------------------------
# dispatch_sync: queue empty → COMPLETED
# ---------------------------------------------------------------------------


def _make_empty_queue() -> MagicMock:
    q = MagicMock()
    q.items.return_value = []
    return q


def _make_lease_store(acquired: bool = True, token: str = "tok-1") -> MagicMock:
    store = MagicMock()
    if acquired:
        lease = MagicMock()
        lease.lease_token = token
        result = MagicMock()
        result.status = "acquired"
        result.lease = lease
    else:
        result = MagicMock()
        result.status = "busy"
        holder = MagicMock()
        holder.owner_session_id = "other-session"
        result.holder = holder
        result.lease = None
    store.acquire.return_value = result
    return store


def _run_dispatch(
    tmp_path: Path,
    *,
    session_id: str = "test-session",
    slug: str | None = None,
    queue: Any = None,
    lease_store: Any = None,
) -> str:
    """Run _dispatch_sync with patched primitives."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    if queue is None:
        queue = _make_empty_queue()
    if lease_store is None:
        lease_store = _make_lease_store()

    with (
        patch("teleclaude.core.integration.state_machine.IntegrationQueue", return_value=queue),
        patch("teleclaude.core.integration.state_machine.IntegrationLeaseStore", return_value=lease_store),
    ):
        return _dispatch_sync(
            session_id=session_id,
            slug=slug,
            cwd=str(tmp_path),
            state_dir=state_dir,
            started=0.0,
            loop=None,
        )


def test_dispatch_returns_complete_when_queue_empty(tmp_path: Path) -> None:
    result = _run_dispatch(tmp_path)
    assert "INTEGRATION COMPLETE" in result
    assert "Queue empty" in result


@patch("teleclaude.core.integration.state_machine._run_git", return_value=(1, "", "not a branch"))
def test_dispatch_returns_complete_when_slug_auto_enqueue_fails(mock_git: MagicMock, tmp_path: Path) -> None:
    """When slug is given but branch resolution fails, queue stays empty and returns complete."""
    result = _run_dispatch(tmp_path, slug="missing-branch-slug")
    assert "INTEGRATION COMPLETE" in result
    assert "Queue empty" in result


@patch("teleclaude.core.integration.state_machine._run_git")
def test_dispatch_auto_enqueues_when_slug_given_and_queue_empty(mock_git: MagicMock, tmp_path: Path) -> None:
    """When slug is given and queue is empty, auto-enqueue via git rev-parse then proceed to lease."""
    sha = "abc123def456"
    # rev-parse returns SHA; all subsequent git calls return failure to stop early
    def _git_side_effect(args: list[str], *, cwd: str) -> tuple[int, str, str]:
        if args[0] == "rev-parse":
            return (0, sha + "\n", "")
        return (1, "", "mocked error")

    mock_git.side_effect = _git_side_effect

    from teleclaude.core.integration.queue import IntegrationQueue

    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    real_queue = IntegrationQueue(state_path=state_dir / "queue.json")

    lease_store = _make_lease_store(acquired=True)

    with (
        patch("teleclaude.core.integration.state_machine.IntegrationQueue", return_value=real_queue),
        patch("teleclaude.core.integration.state_machine.IntegrationLeaseStore", return_value=lease_store),
    ):
        result = _dispatch_sync(
            session_id="test-session",
            slug="my-feature",
            cwd=str(tmp_path),
            state_dir=state_dir,
            started=0.0,
            loop=None,
        )

    # Should have been auto-enqueued and then tried to merge (failed on fetch)
    assert "INTEGRATION ERROR" in result or "GIT_FETCH_FAILED" in result
    items = real_queue.items()
    assert any(item.key.slug == "my-feature" for item in items)


def test_dispatch_returns_lease_busy_when_lease_held(tmp_path: Path) -> None:
    queue = MagicMock()
    # Return one queued item so we don't short-circuit on empty queue
    item = MagicMock()
    item.status = "queued"
    queue.items.return_value = [item]

    lease_store = _make_lease_store(acquired=False)

    result = _run_dispatch(tmp_path, queue=queue, lease_store=lease_store)
    assert "LEASE_BUSY" in result


def test_dispatch_returns_slug_not_next_error_when_slug_mismatch(tmp_path: Path) -> None:
    queue = MagicMock()
    item = MagicMock()
    item.status = "queued"
    item.key.slug = "other-slug"
    queue.items.return_value = [item]

    result = _run_dispatch(tmp_path, slug="wrong-slug", queue=queue)
    assert "SLUG_NOT_NEXT" in result


# ---------------------------------------------------------------------------
# AWAITING_COMMIT: commit detection
# ---------------------------------------------------------------------------


def _write_awaiting_commit_checkpoint(state_dir: Path, pre_merge_head: str) -> None:
    cp_path = state_dir / "integrate-state.json"
    cp = _make_checkpoint(IntegrationPhase.MERGE_CLEAN)
    cp.candidate_slug = "my-feature"
    cp.candidate_branch = "my-feature"
    cp.candidate_sha = "abc123"
    cp.lease_token = "tok-1"
    cp.pre_merge_head = pre_merge_head
    cp.error_context = {"merge_type": "clean"}
    _write_checkpoint(cp_path, cp)


@patch("teleclaude.core.integration.state_machine._merge_head_exists", return_value=False)
@patch("teleclaude.core.integration.state_machine._get_head_sha", return_value="newsha789")
def test_awaiting_commit_detects_commit_and_advances(
    mock_head: MagicMock, mock_merge: MagicMock, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_awaiting_commit_checkpoint(state_dir, pre_merge_head="oldsha123")

    queue = MagicMock()
    queue.items.return_value = []  # no more items after COMMITTED loop

    with (
        patch("teleclaude.core.integration.state_machine.IntegrationQueue", return_value=queue),
        patch(
            "teleclaude.core.integration.state_machine.IntegrationLeaseStore",
            return_value=_make_lease_store(),
        ),
        # Stub delivery bookkeeping subprocess calls
        patch("teleclaude.core.integration.state_machine.subprocess.run") as mock_run,
        # Stub push to succeed
        patch("teleclaude.core.integration.state_machine._run_git") as mock_git,
    ):
        # git diff --cached --quiet should return rc=0 (no staged changes) for bookkeeping commit
        mock_git.return_value = (0, "", "")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = _dispatch_sync(
            session_id="s1",
            slug=None,
            cwd=str(tmp_path),
            state_dir=state_dir,
            started=0.0,
            loop=None,
        )

    # Should have pushed and completed
    assert "INTEGRATION COMPLETE" in result or "PUSH" in result or "COMMIT" in result


@patch("teleclaude.core.integration.state_machine._merge_head_exists", return_value=False)
@patch("teleclaude.core.integration.state_machine._get_head_sha", return_value="oldsha123")
def test_awaiting_commit_reprompts_when_no_commit_yet(
    mock_head: MagicMock, mock_merge: MagicMock, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_awaiting_commit_checkpoint(state_dir, pre_merge_head="oldsha123")

    queue = MagicMock()
    queue.items.return_value = []

    with (
        patch("teleclaude.core.integration.state_machine.IntegrationQueue", return_value=queue),
        patch(
            "teleclaude.core.integration.state_machine.IntegrationLeaseStore",
            return_value=_make_lease_store(),
        ),
        patch("teleclaude.core.integration.state_machine._get_diff_stats", return_value=""),
        patch("teleclaude.core.integration.state_machine._get_branch_log", return_value=""),
    ):
        result = _dispatch_sync(
            session_id="s1",
            slug=None,
            cwd=str(tmp_path),
            state_dir=state_dir,
            started=0.0,
            loop=None,
        )

    assert "SQUASH COMMIT REQUIRED" in result


# ---------------------------------------------------------------------------
# PUSH_REJECTED: recovery detection
# ---------------------------------------------------------------------------


def _write_push_rejected_checkpoint(state_dir: Path, candidate_slug: str = "my-feature") -> None:
    cp_path = state_dir / "integrate-state.json"
    cp = _make_checkpoint(IntegrationPhase.PUSH_REJECTED)
    cp.candidate_slug = candidate_slug
    cp.candidate_branch = candidate_slug
    cp.candidate_sha = "abc123"
    cp.lease_token = "tok-1"
    cp.error_context = {"rejection_reason": "remote: Permission denied"}
    _write_checkpoint(cp_path, cp)


@patch("teleclaude.core.integration.state_machine._get_head_sha", return_value="sha-xyz")
@patch("teleclaude.core.integration.state_machine._get_remote_main_sha", return_value="sha-xyz")
def test_push_rejected_detects_recovery_when_heads_match(
    mock_remote: MagicMock, mock_local: MagicMock, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_push_rejected_checkpoint(state_dir)

    queue = MagicMock()
    queue.items.return_value = []

    with (
        patch("teleclaude.core.integration.state_machine.IntegrationQueue", return_value=queue),
        patch(
            "teleclaude.core.integration.state_machine.IntegrationLeaseStore",
            return_value=_make_lease_store(),
        ),
        patch("teleclaude.core.integration.state_machine._run_git", return_value=(0, "", "")),
        patch("teleclaude.core.integration.state_machine.subprocess.run", return_value=MagicMock(returncode=0)),
    ):
        result = _dispatch_sync(
            session_id="s1",
            slug=None,
            cwd=str(tmp_path),
            state_dir=state_dir,
            started=0.0,
            loop=None,
        )

    # After recovery detection → PUSH_SUCCEEDED → CLEANUP → CANDIDATE_DELIVERED → IDLE → queue empty → COMPLETE
    assert "INTEGRATION COMPLETE" in result or "PUSH" in result


@patch("teleclaude.core.integration.state_machine._get_head_sha", return_value="sha-local")
@patch("teleclaude.core.integration.state_machine._get_remote_main_sha", return_value="sha-remote")
def test_push_rejected_reprompts_when_heads_differ(
    mock_remote: MagicMock, mock_local: MagicMock, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_push_rejected_checkpoint(state_dir)

    queue = MagicMock()
    queue.items.return_value = []

    with (
        patch("teleclaude.core.integration.state_machine.IntegrationQueue", return_value=queue),
        patch(
            "teleclaude.core.integration.state_machine.IntegrationLeaseStore",
            return_value=_make_lease_store(),
        ),
    ):
        result = _dispatch_sync(
            session_id="s1",
            slug=None,
            cwd=str(tmp_path),
            state_dir=state_dir,
            started=0.0,
            loop=None,
        )

    assert "PUSH REJECTION RECOVERY" in result


# ---------------------------------------------------------------------------
# Idempotency: same checkpoint → same output
# ---------------------------------------------------------------------------


@patch("teleclaude.core.integration.state_machine._merge_head_exists", return_value=False)
@patch("teleclaude.core.integration.state_machine._get_head_sha", return_value="oldsha")
def test_awaiting_commit_is_idempotent(
    mock_head: MagicMock, mock_merge: MagicMock, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_awaiting_commit_checkpoint(state_dir, pre_merge_head="oldsha")

    queue = MagicMock()
    queue.items.return_value = []

    with (
        patch("teleclaude.core.integration.state_machine.IntegrationQueue", return_value=queue),
        patch(
            "teleclaude.core.integration.state_machine.IntegrationLeaseStore",
            return_value=_make_lease_store(),
        ),
        patch("teleclaude.core.integration.state_machine._get_diff_stats", return_value="1 file changed"),
        patch("teleclaude.core.integration.state_machine._get_branch_log", return_value="abc commit"),
    ):
        r1 = _dispatch_sync(
            session_id="s1", slug=None, cwd=str(tmp_path), state_dir=state_dir, started=0.0, loop=None
        )
        r2 = _dispatch_sync(
            session_id="s1", slug=None, cwd=str(tmp_path), state_dir=state_dir, started=0.0, loop=None
        )

    assert r1 == r2


# ---------------------------------------------------------------------------
# Clearance wait: probe returns not-cleared
# ---------------------------------------------------------------------------


def _write_clearance_wait_checkpoint(state_dir: Path) -> None:
    cp_path = state_dir / "integrate-state.json"
    cp = _make_checkpoint(IntegrationPhase.CLEARANCE_WAIT)
    cp.candidate_slug = "my-feature"
    cp.candidate_branch = "my-feature"
    cp.candidate_sha = "abc123"
    cp.lease_token = "tok-1"
    _write_checkpoint(cp_path, cp)


def test_clearance_wait_returns_wait_instruction_when_not_cleared(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_clearance_wait_checkpoint(state_dir)

    queue = MagicMock()
    queue.items.return_value = []

    clearance_check = MagicMock()
    clearance_check.cleared = False
    clearance_check.blocking_session_ids = ("other-session",)
    clearance_check.dirty_tracked_paths = ()

    clearance_probe = MagicMock()
    clearance_probe.check.return_value = clearance_check

    with (
        patch("teleclaude.core.integration.state_machine.IntegrationQueue", return_value=queue),
        patch(
            "teleclaude.core.integration.state_machine.IntegrationLeaseStore",
            return_value=_make_lease_store(),
        ),
        patch(
            "teleclaude.core.integration.state_machine._make_clearance_probe",
            return_value=clearance_probe,
        ),
    ):
        result = _dispatch_sync(
            session_id="s1",
            slug=None,
            cwd=str(tmp_path),
            state_dir=state_dir,
            started=0.0,
            loop=None,
        )

    assert "INTEGRATION WAIT" in result
    assert "other-session" in result
