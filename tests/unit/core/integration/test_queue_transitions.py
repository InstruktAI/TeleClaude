"""Tests for integration queue — transition rules and recovery behavior.

Guards against the infinite loop where recovery re-queued an in_progress item
to 'queued', then mark_integrated failed because queued→integrated was not
an allowed transition.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from teleclaude.core.integration.queue import IntegrationQueue, IntegrationQueueError
from teleclaude.core.integration.readiness_projection import CandidateKey


def _make_key(slug: str = "test-slug") -> CandidateKey:
    return CandidateKey(slug=slug, branch=slug, sha="a" * 40)


def _now() -> datetime:
    return datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# queued → integrated transition (fix for infinite loop)
# ---------------------------------------------------------------------------


def test_queued_to_integrated_is_allowed(tmp_path: Path) -> None:
    """After recovery re-queues an in_progress item, mark_integrated must
    succeed on the now-queued item instead of raising an error."""
    queue = IntegrationQueue(state_path=tmp_path / "queue.json")
    key = _make_key()
    queue.enqueue(key=key, ready_at=_now().isoformat())

    # Item is 'queued' (as if recovery re-queued it)
    item = queue.get(key=key)
    assert item is not None
    assert item.status == "queued"

    # mark_integrated should succeed (queued → integrated)
    queue.mark_integrated(key=key, reason="already delivered via squash merge")
    item = queue.get(key=key)
    assert item is not None
    assert item.status == "integrated"


def test_recovery_then_mark_integrated(tmp_path: Path) -> None:
    """Simulates the exact infinite loop scenario: enqueue, pop (in_progress),
    reload queue (recovery re-queues to 'queued'), mark_integrated must succeed."""
    queue_path = tmp_path / "queue.json"
    key = _make_key()

    # First session: enqueue and pop
    q1 = IntegrationQueue(state_path=queue_path)
    q1.enqueue(key=key, ready_at=_now().isoformat())
    q1.pop_next()  # queued → in_progress

    # Simulate re-entry: new IntegrationQueue instance triggers recovery
    q2 = IntegrationQueue(state_path=queue_path)
    item = q2.get(key=key)
    assert item is not None
    assert item.status == "queued"  # recovery re-queued it

    # mark_integrated on the re-queued item must succeed
    q2.mark_integrated(key=key, reason="integrated via state machine")
    item = q2.get(key=key)
    assert item is not None
    assert item.status == "integrated"


def test_integrated_is_terminal(tmp_path: Path) -> None:
    """Items in 'integrated' status cannot transition to any other status."""
    queue = IntegrationQueue(state_path=tmp_path / "queue.json")
    key = _make_key()
    queue.enqueue(key=key, ready_at=_now().isoformat())
    queue.mark_integrated(key=key, reason="test")

    with pytest.raises(IntegrationQueueError):
        queue._set_status(key=key, to_status="queued", reason="attempt re-queue", now=None)
