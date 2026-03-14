"""Characterization tests for teleclaude.core.integration.checkpoint."""

from __future__ import annotations

from pathlib import Path

from teleclaude.core.integration.checkpoint import (
    IntegrationCheckpoint,
    IntegrationPhase,
    _read_checkpoint,
    _write_checkpoint,
)

# ---------------------------------------------------------------------------
# IntegrationPhase
# ---------------------------------------------------------------------------


def test_integration_phase_values_are_strings() -> None:
    for phase in IntegrationPhase:
        assert isinstance(phase.value, str)


def test_integration_phase_idle_is_initial() -> None:
    assert IntegrationPhase.IDLE.value == "idle"


def test_integration_phase_all_expected_phases_present() -> None:
    phase_values = {p.value for p in IntegrationPhase}
    expected = {"idle", "candidate_dequeued", "merge_clean", "merge_conflicted", "committed", "completed"}
    assert expected.issubset(phase_values)


# ---------------------------------------------------------------------------
# _read_checkpoint
# ---------------------------------------------------------------------------


def test_read_checkpoint_returns_idle_when_absent(tmp_path: Path) -> None:
    checkpoint = _read_checkpoint(tmp_path / "checkpoint.json")
    assert checkpoint.phase == IntegrationPhase.IDLE.value
    assert checkpoint.candidate_slug is None
    assert checkpoint.items_processed == 0


def test_read_checkpoint_returns_idle_for_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    path.write_text("", encoding="utf-8")
    checkpoint = _read_checkpoint(path)
    assert checkpoint.phase == IntegrationPhase.IDLE.value


def test_read_checkpoint_returns_idle_for_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    path.write_text("not json", encoding="utf-8")
    # Should not raise — returns fresh default
    checkpoint = _read_checkpoint(path)
    assert checkpoint.phase == IntegrationPhase.IDLE.value


# ---------------------------------------------------------------------------
# _write_checkpoint / round-trip
# ---------------------------------------------------------------------------


def test_write_and_read_checkpoint_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    checkpoint = IntegrationCheckpoint(
        phase=IntegrationPhase.MERGE_CLEAN.value,
        candidate_slug="my-slug",
        candidate_branch="my-branch",
        candidate_sha="abc123",
        lease_token="lease-tok",
        items_processed=2,
        items_blocked=1,
        started_at="2024-01-01T12:00:00+00:00",
        last_updated_at="2024-01-01T12:00:00+00:00",
        error_context={"merge_type": "clean"},
        pre_merge_head="deadbeef",
    )
    _write_checkpoint(path, checkpoint)
    restored = _read_checkpoint(path)
    assert restored.phase == IntegrationPhase.MERGE_CLEAN.value
    assert restored.candidate_slug == "my-slug"
    assert restored.candidate_branch == "my-branch"
    assert restored.candidate_sha == "abc123"
    assert restored.items_processed == 2
    assert restored.items_blocked == 1
    assert restored.lease_token == "lease-tok"
    assert restored.error_context == {"merge_type": "clean"}
    assert restored.pre_merge_head == "deadbeef"


def test_write_checkpoint_updates_last_updated_at(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    checkpoint = IntegrationCheckpoint(
        phase=IntegrationPhase.IDLE.value,
        candidate_slug=None,
        candidate_branch=None,
        candidate_sha=None,
        lease_token=None,
        items_processed=0,
        items_blocked=0,
        started_at="2024-01-01T12:00:00+00:00",
        last_updated_at="2024-01-01T12:00:00+00:00",
        error_context=None,
        pre_merge_head=None,
    )
    _write_checkpoint(path, checkpoint)
    restored = _read_checkpoint(path)
    # _write_checkpoint stamps last_updated_at with current time — must differ from input
    assert restored.last_updated_at != "2024-01-01T12:00:00+00:00"
    from datetime import datetime

    datetime.fromisoformat(restored.last_updated_at)  # must be valid ISO-8601


def test_write_checkpoint_is_atomic(tmp_path: Path) -> None:
    """Verify no .tmp file left behind after successful write."""
    path = tmp_path / "checkpoint.json"
    checkpoint = IntegrationCheckpoint(
        phase=IntegrationPhase.IDLE.value,
        candidate_slug=None,
        candidate_branch=None,
        candidate_sha=None,
        lease_token=None,
        items_processed=0,
        items_blocked=0,
        started_at="2024-01-01T12:00:00+00:00",
        last_updated_at="2024-01-01T12:00:00+00:00",
        error_context=None,
        pre_merge_head=None,
    )
    _write_checkpoint(path, checkpoint)
    assert path.exists()
    tmp_path_candidate = path.with_suffix(path.suffix + ".tmp")
    assert not tmp_path_candidate.exists()
