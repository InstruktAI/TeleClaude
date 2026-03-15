from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from teleclaude.core import db_models
from teleclaude.core.db import Db
from teleclaude.core.db._hooks import DbHooksMixin

pytestmark = pytest.mark.asyncio


async def test_get_agent_availability_restores_expired_unavailable_row(db: Db) -> None:
    expired = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    await db.mark_agent_unavailable("claude", expired, "quota_exhausted")

    availability = await db.get_agent_availability("claude")

    assert availability == {
        "available": True,
        "unavailable_until": None,
        "degraded_until": None,
        "reason": None,
        "status": "available",
    }


async def test_mark_agent_degraded_prefixes_reason_and_mark_agent_available_clears_it(db: Db) -> None:
    future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    await db.mark_agent_degraded("codex", "rate_limited", degraded_until=future)

    degraded = await db.get_agent_availability("codex")
    await db.mark_agent_available("codex")
    restored = await db.get_agent_availability("codex")

    assert degraded == {
        "available": True,
        "unavailable_until": None,
        "degraded_until": future,
        "reason": "degraded:rate_limited",
        "status": "degraded",
    }
    assert restored == {
        "available": True,
        "unavailable_until": None,
        "degraded_until": None,
        "reason": None,
        "status": "available",
    }


async def test_clear_expired_agent_availability_only_resets_expired_rows(db: Db) -> None:
    expired = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    await db.mark_agent_unavailable("claude", future, "quota_exhausted")
    await db.mark_agent_degraded("gemini", "overloaded", degraded_until=expired)

    cleared = await db.clear_expired_agent_availability()
    claude = await db.get_agent_availability("claude")
    gemini = await db.get_agent_availability("gemini")

    assert cleared == 1
    assert claude is not None
    assert claude["status"] == "unavailable"
    assert gemini == {
        "available": True,
        "unavailable_until": None,
        "degraded_until": None,
        "reason": None,
        "status": "available",
    }


async def test_hook_outbox_fetch_and_single_claim_expose_due_rows(db: Db) -> None:
    row_id = await db.enqueue_hook_event("sess-001", "session.updated", {"delta": 1})
    now_iso = datetime.now(UTC).isoformat()
    lock_cutoff_iso = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()

    batch = await db.fetch_hook_outbox_batch(now_iso=now_iso, limit=10, lock_cutoff_iso=lock_cutoff_iso)
    claimed = await db.claim_hook_outbox(row_id, now_iso=now_iso, lock_cutoff_iso=lock_cutoff_iso)

    assert batch == [
        {
            "id": row_id,
            "session_id": "sess-001",
            "event_type": "session.updated",
            "payload": json.dumps({"delta": 1}),
            "created_at": batch[0]["created_at"],
            "attempt_count": 0,
        }
    ]
    assert claimed is True


async def test_hook_outbox_batch_claim_retry_and_delivery_follow_persisted_state(db: Db) -> None:
    first_id = await db.enqueue_hook_event("sess-001", "session.updated", {"n": 1})
    second_id = await db.enqueue_hook_event("sess-002", "session.updated", {"n": 2})
    now_iso = datetime.now(UTC).isoformat()
    future = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    claimed = await db.claim_hook_outbox_batch(
        [first_id, second_id],
        now_iso=now_iso,
        lock_cutoff_iso=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    )

    await db.mark_hook_outbox_failed(first_id, attempt_count=2, next_attempt_at=future, error="timeout")
    await db.mark_hook_outbox_delivered(second_id, error="prior-failure")

    retry_batch = await db.fetch_hook_outbox_batch(
        now_iso=(datetime.now(UTC) + timedelta(minutes=11)).isoformat(),
        limit=10,
        lock_cutoff_iso=now_iso,
    )

    assert claimed == {first_id, second_id}
    assert retry_batch == [
        {
            "id": first_id,
            "session_id": "sess-001",
            "event_type": "session.updated",
            "payload": json.dumps({"n": 1}),
            "created_at": retry_batch[0]["created_at"],
            "attempt_count": 2,
        }
    ]

    async with db._session() as session:
        delivered = await session.get(db_models.HookOutbox, second_id)

    assert delivered is not None
    assert delivered.delivered_at is not None
    assert delivered.last_error == "prior-failure"
    assert DbHooksMixin._parse_iso_datetime("not-an-iso-string") is None
