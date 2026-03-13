"""Tests for integration state machine — counter reset on session entry.

Guards against the bug where items_processed/items_blocked accumulated across
integrator sessions because the checkpoint file was never reset between runs.
"""

from __future__ import annotations

import re
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from teleclaude.core.integration.state_machine import (
    IntegrationCheckpoint,
    IntegrationPhase,
    _dispatch_sync,
    _write_checkpoint,
)


def _write_stale_idle_checkpoint(state_dir: Path, *, items_processed: int, items_blocked: int) -> None:
    """Seed an IDLE checkpoint with non-zero counters from a 'previous run'."""
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
    _write_checkpoint(state_dir / "integrate-state.json", cp)


def _extract_processed_count(output: str) -> int:
    """Parse 'Candidates processed: N' from state machine output."""
    match = re.search(r"Candidates processed:\s*(\d+)", output)
    assert match, f"Expected 'Candidates processed' in output:\n{output}"
    return int(match.group(1))


def _extract_blocked_count(output: str) -> int:
    """Parse 'Candidates blocked: N' from state machine output."""
    match = re.search(r"Candidates blocked:\s*(\d+)", output)
    assert match, f"Expected 'Candidates blocked' in output:\n{output}"
    return int(match.group(1))


# ---------------------------------------------------------------------------
# _dispatch_sync counter reset — exercises the real production path
# ---------------------------------------------------------------------------


@patch("teleclaude.core.integration.state_machine._run_git", return_value=(0, "", ""))
def test_dispatch_resets_stale_counters_on_idle_entry(_mock_git: object, tmp_path: Path) -> None:
    """_dispatch_sync zeroes items_processed and items_blocked when it enters
    with an IDLE checkpoint, so the final report reflects only this run's work.

    This is the exact regression scenario: a previous integrator session left
    items_processed=9 in the checkpoint, and the next session reported
    'Candidates processed: 9' despite processing zero candidates.
    """
    _write_stale_idle_checkpoint(tmp_path, items_processed=9, items_blocked=2)

    output = _dispatch_sync(
        session_id="test-session",
        slug=None,
        cwd=str(tmp_path),
        state_dir=tmp_path,
        started=perf_counter(),
    )

    assert _extract_processed_count(output) == 0
    assert _extract_blocked_count(output) == 0


@patch("teleclaude.core.integration.state_machine._run_git", return_value=(0, "", ""))
def test_dispatch_preserves_counters_on_mid_run_reentry(_mock_git: object, tmp_path: Path) -> None:
    """When the checkpoint is NOT IDLE (crash recovery), counters must survive
    so the resumed session reports accurate totals for its run.

    Simulates a crash after 3 candidates were processed: the checkpoint is in
    CANDIDATE_DELIVERED phase. On re-entry, _dispatch_sync must not zero the
    counters — it should transition through CANDIDATE_DELIVERED back to IDLE
    and then report the preserved count.
    """
    cp = IntegrationCheckpoint(
        phase=IntegrationPhase.CANDIDATE_DELIVERED.value,
        candidate_slug="some-slug",
        candidate_branch="some-slug",
        candidate_sha="abc123" + "0" * 34,
        lease_token=None,
        items_processed=3,
        items_blocked=1,
        started_at="2026-01-01T00:00:00+00:00",
        last_updated_at="2026-01-01T00:00:00+00:00",
        error_context=None,
        pre_merge_head=None,
    )
    _write_checkpoint(tmp_path / "integrate-state.json", cp)

    output = _dispatch_sync(
        session_id="test-session",
        slug=None,
        cwd=str(tmp_path),
        state_dir=tmp_path,
        started=perf_counter(),
    )

    # CANDIDATE_DELIVERED transitions to IDLE, then IDLE finds no candidates
    # (no trees/ directory). Counters from the crashed run are preserved.
    assert _extract_processed_count(output) == 3
    assert _extract_blocked_count(output) == 1
