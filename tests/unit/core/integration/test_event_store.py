"""Characterization tests for teleclaude.core.integration.event_store."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.core.integration.event_store import (
    AppendResult,
    IntegrationEventStore,
    IntegrationEventStoreError,
)
from teleclaude.core.integration.events import build_integration_event

_REVIEW_APPROVED_PAYLOAD = {
    "slug": "my-slug",
    "approved_at": "2024-01-01T12:00:00+00:00",
    "review_round": 1,
    "reviewer_session_id": "session-abc",
}

_BRANCH_PUSHED_PAYLOAD = {
    "branch": "feature-branch",
    "sha": "deadbeef",
    "remote": "origin",
    "pushed_at": "2024-01-01T12:00:00+00:00",
    "pusher": "agent-1",
}


def _make_store(tmp_path: Path) -> IntegrationEventStore:
    return IntegrationEventStore(tmp_path / "events.jsonl")


# ---------------------------------------------------------------------------
# append
# ---------------------------------------------------------------------------


def test_append_first_event_returns_appended(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    event = build_integration_event("review_approved", _REVIEW_APPROVED_PAYLOAD)
    result = store.append(event)
    assert isinstance(result, AppendResult)
    assert result.status == "appended"
    assert result.event is event


def test_append_duplicate_event_returns_duplicate(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    event = build_integration_event("review_approved", _REVIEW_APPROVED_PAYLOAD)
    store.append(event)
    result = store.append(event)
    assert result.status == "duplicate"


def test_append_increments_event_count(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    e1 = build_integration_event("review_approved", _REVIEW_APPROVED_PAYLOAD)
    e2 = build_integration_event("branch_pushed", _BRANCH_PUSHED_PAYLOAD)
    store.append(e1)
    store.append(e2)
    assert store.event_count == 2


def test_append_duplicate_does_not_increment_count(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    event = build_integration_event("review_approved", _REVIEW_APPROVED_PAYLOAD)
    store.append(event)
    store.append(event)
    assert store.event_count == 1


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------


def test_replay_returns_all_appended_events_in_order(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    e1 = build_integration_event("review_approved", _REVIEW_APPROVED_PAYLOAD)
    e2 = build_integration_event("branch_pushed", _BRANCH_PUSHED_PAYLOAD)
    store.append(e1)
    store.append(e2)
    events = store.replay()
    assert len(events) == 2
    assert events[0].event_type == "review_approved"
    assert events[1].event_type == "branch_pushed"


def test_replay_empty_store_returns_empty_tuple(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.replay() == ()


# ---------------------------------------------------------------------------
# persistence across reload
# ---------------------------------------------------------------------------


def test_store_persists_events_across_reload(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    s1 = IntegrationEventStore(path)
    event = build_integration_event("review_approved", _REVIEW_APPROVED_PAYLOAD)
    s1.append(event)

    s2 = IntegrationEventStore(path)
    assert s2.event_count == 1
    assert s2.replay()[0].idempotency_key == event.idempotency_key


# ---------------------------------------------------------------------------
# corrupt log
# ---------------------------------------------------------------------------


def test_corrupt_log_raises_on_load(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("not valid json\n", encoding="utf-8")
    store = IntegrationEventStore(path)
    with pytest.raises(IntegrationEventStoreError):
        store.event_count  # triggers _ensure_loaded


def test_idempotency_key_collision_raises(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    e1 = build_integration_event("review_approved", _REVIEW_APPROVED_PAYLOAD, idempotency_key="shared-key")
    e2 = build_integration_event("branch_pushed", _BRANCH_PUSHED_PAYLOAD, idempotency_key="shared-key")
    store.append(e1)
    with pytest.raises(IntegrationEventStoreError):
        store.append(e2)
