"""Unit tests for hook outbox database helpers."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core.db import Db


@pytest.mark.asyncio
async def test_hook_outbox_lifecycle(tmp_path: Path) -> None:
    """Test enqueue, claim, fail, and deliver lifecycle for hook outbox rows."""
    db = Db(str(tmp_path / "teleclaude.db"))
    await db.initialize()

    row_id = await db.enqueue_hook_event("sess-123", "stop", {"foo": "bar"})

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    lock_cutoff = (now - timedelta(seconds=1)).isoformat()

    rows = await db.fetch_hook_outbox_batch(now_iso, 10, lock_cutoff)
    assert len(rows) == 1
    assert rows[0]["id"] == row_id

    claimed = await db.claim_hook_outbox(row_id, now_iso, lock_cutoff)
    assert claimed is True

    next_attempt = (now + timedelta(seconds=30)).isoformat()
    await db.mark_hook_outbox_failed(row_id, 1, next_attempt, "boom")

    rows = await db.fetch_hook_outbox_batch(now_iso, 10, lock_cutoff)
    assert rows == []

    await db.mark_hook_outbox_delivered(row_id)

    rows = await db.fetch_hook_outbox_batch(now_iso, 10, lock_cutoff)
    assert rows == []

    await db.close()
