"""Characterization tests for teleclaude.core.integration.queue."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from teleclaude.core.integration.queue import (
    IntegrationQueue,
    IntegrationQueueError,
    QueueTransition,
    default_integration_queue_path,
    default_integration_state_dir,
)
from teleclaude.core.integration.readiness_projection import CandidateKey

_NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
_READY_AT = "2024-01-01T10:00:00+00:00"


def _make_key(slug: str = "slug-a", branch: str = "branch-a", sha: str = "sha-a") -> CandidateKey:
    return CandidateKey(slug=slug, branch=branch, sha=sha)


def _make_queue(tmp_path: Path) -> IntegrationQueue:
    return IntegrationQueue(state_path=tmp_path / "queue.json")


# ---------------------------------------------------------------------------
# default paths
# ---------------------------------------------------------------------------


def test_default_integration_state_dir_returns_path() -> None:
    path = default_integration_state_dir()
    assert isinstance(path, Path)
    assert "teleclaude" in str(path) or "integration" in str(path)


def test_default_integration_queue_path_ends_with_queue_json() -> None:
    path = default_integration_queue_path()
    assert path.name == "queue.json"


# ---------------------------------------------------------------------------
# IntegrationQueue.enqueue
# ---------------------------------------------------------------------------


def test_enqueue_adds_item_with_queued_status(tmp_path: Path) -> None:
    q = _make_queue(tmp_path)
    key = _make_key()
    item = q.enqueue(key=key, ready_at=_READY_AT, now=_NOW)
    assert item.status == "queued"
    assert item.key == key


def test_enqueue_is_idempotent(tmp_path: Path) -> None:
    q = _make_queue(tmp_path)
    key = _make_key()
    item1 = q.enqueue(key=key, ready_at=_READY_AT, now=_NOW)
    item2 = q.enqueue(key=key, ready_at=_READY_AT, now=_NOW)
    assert item1 == item2
    assert len(q.items()) == 1


def test_enqueue_rejects_invalid_ready_at(tmp_path: Path) -> None:
    q = _make_queue(tmp_path)
    with pytest.raises(ValueError):
        q.enqueue(key=_make_key(), ready_at="not-a-timestamp", now=_NOW)


# ---------------------------------------------------------------------------
# IntegrationQueue.pop_next
# ---------------------------------------------------------------------------


def test_pop_next_returns_none_when_empty(tmp_path: Path) -> None:
    q = _make_queue(tmp_path)
    assert q.pop_next(now=_NOW) is None


def test_pop_next_sets_item_to_in_progress(tmp_path: Path) -> None:
    q = _make_queue(tmp_path)
    key = _make_key()
    q.enqueue(key=key, ready_at=_READY_AT, now=_NOW)
    item = q.pop_next(now=_NOW)
    assert item is not None
    assert item.status == "in_progress"
    assert item.key == key


def test_pop_next_returns_fifo_order(tmp_path: Path) -> None:
    q = _make_queue(tmp_path)
    k1 = _make_key(slug="a")
    k2 = _make_key(slug="b")
    q.enqueue(key=k1, ready_at="2024-01-01T10:00:00+00:00", now=_NOW)
    q.enqueue(key=k2, ready_at="2024-01-01T11:00:00+00:00", now=_NOW)
    first = q.pop_next(now=_NOW)
    assert first is not None
    assert first.key.slug == "a"


def test_pop_next_returns_none_when_all_in_progress(tmp_path: Path) -> None:
    q = _make_queue(tmp_path)
    key = _make_key()
    q.enqueue(key=key, ready_at=_READY_AT, now=_NOW)
    q.pop_next(now=_NOW)
    assert q.pop_next(now=_NOW) is None


# ---------------------------------------------------------------------------
# IntegrationQueue status transitions
# ---------------------------------------------------------------------------


def test_mark_integrated_transitions_in_progress_to_integrated(tmp_path: Path) -> None:
    q = _make_queue(tmp_path)
    key = _make_key()
    q.enqueue(key=key, ready_at=_READY_AT, now=_NOW)
    q.pop_next(now=_NOW)
    q.mark_integrated(key=key, reason="delivered", now=_NOW)
    item = q.get(key=key)
    assert item is not None
    assert item.status == "integrated"


def test_mark_blocked_transitions_in_progress_to_blocked(tmp_path: Path) -> None:
    q = _make_queue(tmp_path)
    key = _make_key()
    q.enqueue(key=key, ready_at=_READY_AT, now=_NOW)
    q.pop_next(now=_NOW)
    q.mark_blocked(key=key, reason="conflict", now=_NOW)
    item = q.get(key=key)
    assert item is not None
    assert item.status == "blocked"


def test_resume_blocked_transitions_blocked_to_queued(tmp_path: Path) -> None:
    q = _make_queue(tmp_path)
    key = _make_key()
    q.enqueue(key=key, ready_at=_READY_AT, now=_NOW)
    q.pop_next(now=_NOW)
    q.mark_blocked(key=key, reason="conflict", now=_NOW)
    q.resume_blocked(key=key, reason="remediated", now=_NOW)
    item = q.get(key=key)
    assert item is not None
    assert item.status == "queued"


def test_invalid_transition_raises(tmp_path: Path) -> None:
    q = _make_queue(tmp_path)
    key = _make_key()
    q.enqueue(key=key, ready_at=_READY_AT, now=_NOW)
    with pytest.raises(IntegrationQueueError):
        q.mark_blocked(key=key, reason="conflict", now=_NOW)  # queued → blocked is invalid


# ---------------------------------------------------------------------------
# IntegrationQueue persistence
# ---------------------------------------------------------------------------


def test_queue_persists_across_reload(tmp_path: Path) -> None:
    path = tmp_path / "queue.json"
    q1 = IntegrationQueue(state_path=path)
    key = _make_key()
    q1.enqueue(key=key, ready_at=_READY_AT, now=_NOW)
    q2 = IntegrationQueue(state_path=path)
    item = q2.get(key=key)
    assert item is not None
    assert item.status == "queued"


def test_queue_recovers_in_progress_to_queued_on_reload(tmp_path: Path) -> None:
    path = tmp_path / "queue.json"
    q1 = IntegrationQueue(state_path=path)
    key = _make_key()
    q1.enqueue(key=key, ready_at=_READY_AT, now=_NOW)
    q1.pop_next(now=_NOW)  # set to in_progress
    q2 = IntegrationQueue(state_path=path)
    item = q2.get(key=key)
    assert item is not None
    assert item.status == "queued"


# ---------------------------------------------------------------------------
# IntegrationQueue.transitions
# ---------------------------------------------------------------------------


def test_transitions_records_history(tmp_path: Path) -> None:
    q = _make_queue(tmp_path)
    key = _make_key()
    q.enqueue(key=key, ready_at=_READY_AT, now=_NOW)
    q.pop_next(now=_NOW)
    transitions = q.transitions()
    assert len(transitions) >= 2
    assert all(isinstance(t, QueueTransition) for t in transitions)
