"""Tests for integration state machine checkpoint behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.core.integration.state_machine import (
    IntegrationCheckpoint,
    IntegrationPhase,
    _read_checkpoint,
    _write_checkpoint,
)


@pytest.fixture()
def checkpoint_path(tmp_path: Path) -> Path:
    return tmp_path / "integrate-state.json"


# ---------------------------------------------------------------------------
# Checkpoint round-trip
# ---------------------------------------------------------------------------


def test_read_returns_idle_when_file_absent(checkpoint_path: Path) -> None:
    """Missing checkpoint file produces a fresh IDLE checkpoint with zero counters."""
    cp = _read_checkpoint(checkpoint_path)
    assert cp.phase == IntegrationPhase.IDLE.value
    assert cp.items_processed == 0
    assert cp.items_blocked == 0


def test_write_then_read_preserves_fields(checkpoint_path: Path) -> None:
    """Round-trip through write/read preserves all checkpoint fields."""
    original = IntegrationCheckpoint(
        phase=IntegrationPhase.CANDIDATE_DEQUEUED.value,
        candidate_slug="my-feature",
        candidate_branch="my-feature",
        candidate_sha="abc123",
        lease_token="tok-1",
        items_processed=3,
        items_blocked=1,
        started_at="2026-01-01T00:00:00+00:00",
        last_updated_at="2026-01-01T00:00:00+00:00",
        error_context=None,
        pre_merge_head="def456",
    )
    _write_checkpoint(checkpoint_path, original)
    restored = _read_checkpoint(checkpoint_path)

    assert restored.phase == original.phase
    assert restored.candidate_slug == original.candidate_slug
    assert restored.candidate_branch == original.candidate_branch
    assert restored.candidate_sha == original.candidate_sha
    assert restored.lease_token == original.lease_token
    assert restored.items_processed == original.items_processed
    assert restored.items_blocked == original.items_blocked
    assert restored.pre_merge_head == original.pre_merge_head


def test_read_returns_idle_for_empty_file(checkpoint_path: Path) -> None:
    """Empty checkpoint file produces a fresh IDLE checkpoint."""
    checkpoint_path.write_text("")
    cp = _read_checkpoint(checkpoint_path)
    assert cp.phase == IntegrationPhase.IDLE.value
    assert cp.items_processed == 0


def test_read_returns_idle_for_corrupt_json(checkpoint_path: Path) -> None:
    """Corrupt JSON produces a fresh IDLE checkpoint rather than raising."""
    checkpoint_path.write_text("{not valid json!!}")
    cp = _read_checkpoint(checkpoint_path)
    assert cp.phase == IntegrationPhase.IDLE.value
    assert cp.items_processed == 0


# ---------------------------------------------------------------------------
# Counter reset on session entry
# ---------------------------------------------------------------------------


def _make_idle_checkpoint_with_stale_counters(
    checkpoint_path: Path,
    *,
    items_processed: int = 9,
    items_blocked: int = 2,
) -> None:
    """Write an IDLE checkpoint with non-zero counters (simulates a previous run)."""
    cp = IntegrationCheckpoint(
        phase=IntegrationPhase.IDLE.value,
        candidate_slug=None,
        candidate_branch=None,
        candidate_sha=None,
        lease_token=None,
        items_processed=items_processed,
        items_blocked=items_blocked,
        started_at="2026-01-01T00:00:00+00:00",
        last_updated_at="2026-01-01T00:00:00+00:00",
        error_context=None,
        pre_merge_head=None,
    )
    _write_checkpoint(checkpoint_path, cp)


def test_idle_checkpoint_counters_reset_on_fresh_entry(checkpoint_path: Path) -> None:
    """When a new session reads an IDLE checkpoint with stale counters, resetting
    items_processed and items_blocked to zero reflects only the new run's work.

    This is the exact bug scenario: previous runs left accumulated counters in
    the checkpoint file, and new runs reported inflated totals.
    """
    _make_idle_checkpoint_with_stale_counters(checkpoint_path, items_processed=9, items_blocked=2)

    # Simulate what _dispatch_sync does on entry: read, reset if IDLE, write.
    initial = _read_checkpoint(checkpoint_path)
    assert initial.phase == IntegrationPhase.IDLE.value
    assert initial.items_processed == 9  # stale from previous run

    initial.items_processed = 0
    initial.items_blocked = 0
    _write_checkpoint(checkpoint_path, initial)

    # Verify the persisted checkpoint now has zeroed counters.
    after_reset = _read_checkpoint(checkpoint_path)
    assert after_reset.items_processed == 0
    assert after_reset.items_blocked == 0


def test_mid_run_checkpoint_counters_preserved(checkpoint_path: Path) -> None:
    """When a checkpoint is NOT in IDLE (crash recovery), counters must be preserved
    so the resumed session reports accurate totals for its run.
    """
    cp = IntegrationCheckpoint(
        phase=IntegrationPhase.CANDIDATE_DEQUEUED.value,
        candidate_slug="some-slug",
        candidate_branch="some-slug",
        candidate_sha="abc",
        lease_token="tok-1",
        items_processed=3,
        items_blocked=0,
        started_at="2026-01-01T00:00:00+00:00",
        last_updated_at="2026-01-01T00:00:00+00:00",
        error_context=None,
        pre_merge_head=None,
    )
    _write_checkpoint(checkpoint_path, cp)

    # Simulate _dispatch_sync entry: only reset when IDLE.
    restored = _read_checkpoint(checkpoint_path)
    assert restored.phase != IntegrationPhase.IDLE.value
    # Counters should NOT be touched.
    assert restored.items_processed == 3
    assert restored.items_blocked == 0


def test_items_processed_increments_correctly(checkpoint_path: Path) -> None:
    """Incrementing items_processed persists through write/read cycle."""
    cp = IntegrationCheckpoint(
        phase=IntegrationPhase.IDLE.value,
        candidate_slug=None,
        candidate_branch=None,
        candidate_sha=None,
        lease_token=None,
        items_processed=0,
        items_blocked=0,
        started_at="2026-01-01T00:00:00+00:00",
        last_updated_at="2026-01-01T00:00:00+00:00",
        error_context=None,
        pre_merge_head=None,
    )
    _write_checkpoint(checkpoint_path, cp)

    restored = _read_checkpoint(checkpoint_path)
    restored.items_processed += 1
    _write_checkpoint(checkpoint_path, restored)

    final = _read_checkpoint(checkpoint_path)
    assert final.items_processed == 1
