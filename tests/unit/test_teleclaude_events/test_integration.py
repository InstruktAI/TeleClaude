"""Integration test: producer → Redis Stream → processor → SQLite.

Skipped when Redis is unavailable.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from teleclaude_events.catalog import build_default_catalog
from teleclaude_events.cartridges import DeduplicationCartridge, NotificationProjectorCartridge
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude_events.pipeline import Pipeline, PipelineContext
from teleclaude_events.processor import EventProcessor
from teleclaude_events.producer import EventProducer


@pytest.fixture
async def redis_client():  # type: ignore[misc]
    """Attempt to connect to Redis; skip test if unavailable."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.Redis.from_url("redis://localhost:6379", socket_connect_timeout=1)
        await client.ping()
        yield client
        await client.aclose()
    except Exception:
        pytest.skip("Redis not available")


@pytest.fixture
async def db(tmp_path: Path) -> EventDB:  # type: ignore[misc]
    event_db = EventDB(db_path=tmp_path / "integration_test.db")
    await event_db.init()
    yield event_db  # type: ignore[misc]
    await event_db.close()


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_emit_and_process_integration(redis_client, db: EventDB, tmp_path: Path) -> None:
    """Emit an event, process it through the pipeline, verify it lands in SQLite."""
    catalog = build_default_catalog()

    # Use unique stream name to avoid test pollution
    stream_name = f"teleclaude:events:test:{tmp_path.name}"

    # Clean up any leftover data
    await redis_client.delete(stream_name)

    producer = EventProducer(redis_client=redis_client, stream=stream_name)
    processed_ids: list[int] = []

    async def on_notification(notification_id: int, event_type: str, was_created: bool, is_meaningful: bool) -> None:
        processed_ids.append(notification_id)

    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[on_notification])
    pipeline = Pipeline([DeduplicationCartridge(), NotificationProjectorCartridge()], context)

    shutdown_event = asyncio.Event()
    processor = EventProcessor(
        redis_client=redis_client,
        pipeline=pipeline,
        stream=stream_name,
        consumer_name="test-consumer",
    )

    # Start processor first so the consumer group exists before we emit
    processor_task = asyncio.create_task(processor.start(shutdown_event))
    # Give processor time to set up the consumer group
    await asyncio.sleep(0.1)

    # Now emit the event
    envelope = EventEnvelope(
        event="system.daemon.restarted",
        source="test",
        level=EventLevel.INFRASTRUCTURE,
        domain="system",
        visibility=EventVisibility.CLUSTER,
        payload={"computer": "test-machine", "pid": 12345},
    )
    await producer.emit(envelope)

    # Give processor time to consume the message (blocking XREADGROUP has 1000ms block)
    await asyncio.sleep(1.5)
    shutdown_event.set()
    try:
        await asyncio.wait_for(processor_task, timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    # Verify notification was created
    assert len(processed_ids) >= 1
    row = await db.get_notification(processed_ids[0])
    assert row is not None
    assert row["event_type"] == "system.daemon.restarted"

    # Cleanup
    await redis_client.delete(stream_name)
