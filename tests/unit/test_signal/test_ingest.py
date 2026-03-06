"""Unit tests for the signal ingest cartridge."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude_events.catalog import EventCatalog
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope, EventLevel
from teleclaude_events.pipeline import PipelineContext
from teleclaude_events.signal.sources import SignalSourceConfig, SourceConfig, SourceType


RSS_FIXTURE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Test Channel</title>
        <item>
          <title>First Article</title>
          <link>https://example.com/first</link>
          <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
          <description>First article description.</description>
        </item>
        <item>
          <title>Second Article</title>
          <link>https://example.com/second</link>
          <pubDate>Tue, 02 Jan 2024 00:00:00 GMT</pubDate>
          <description>Second article description.</description>
        </item>
        <item>
          <title>Third Article</title>
          <link>https://example.com/third</link>
          <pubDate>Wed, 03 Jan 2024 00:00:00 GMT</pubDate>
          <description>Third article description.</description>
        </item>
      </channel>
    </rss>
""")


def _make_ai_client(summary: str = "Test summary", tags: list[str] | None = None) -> MagicMock:
    ai = MagicMock()
    ai.summarise = AsyncMock(return_value=summary)
    ai.extract_tags = AsyncMock(return_value=tags or ["test", "article"])
    ai.embed = AsyncMock(return_value=None)
    return ai


def _make_fetch_result(body: str) -> MagicMock:
    from teleclaude_events.signal.fetch import FetchResult
    return FetchResult(url="https://example.com/feed.xml", status=200, content_type="application/rss+xml", body=body, error=None)


@pytest.fixture
async def db(tmp_path: Path) -> EventDB:  # type: ignore[misc]
    event_db = EventDB(db_path=tmp_path / "test_ingest.db")
    await event_db.init()
    yield event_db  # type: ignore[misc]
    await event_db.close()


@pytest.fixture
def source_config() -> SignalSourceConfig:
    return SignalSourceConfig(
        sources=[SourceConfig(type=SourceType.RSS, url="https://example.com/feed.xml", label="test-feed")],
        max_items_per_pull=10,
        ai_concurrency=3,
    )


@pytest.mark.asyncio
async def test_pull_ingests_new_items(db: EventDB, source_config: SignalSourceConfig) -> None:
    from company.cartridges.signal.ingest import SignalIngestCartridge

    ai = _make_ai_client()
    signal_db = db.signal
    cartridge = SignalIngestCartridge(config=source_config, ai=ai, signal_db=signal_db)

    emitted: list[EventEnvelope] = []

    async def mock_emit(env: EventEnvelope) -> None:
        emitted.append(env)

    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[], emit=mock_emit)

    with patch("company.cartridges.signal.ingest.fetch_url", new=AsyncMock(return_value=_make_fetch_result(RSS_FIXTURE))):
        count = await cartridge.pull(context)

    assert count == 3
    assert len(emitted) == 3
    for env in emitted:
        assert env.event == "signal.ingest.received"
        assert env.description == "Test summary"
        assert "tags" in env.payload
        assert env.payload["tags"] == ["test", "article"]


@pytest.mark.asyncio
async def test_pull_skips_duplicate_items(db: EventDB, source_config: SignalSourceConfig) -> None:
    from company.cartridges.signal.ingest import SignalIngestCartridge

    ai = _make_ai_client()
    signal_db = db.signal
    cartridge = SignalIngestCartridge(config=source_config, ai=ai, signal_db=signal_db)

    emitted: list[EventEnvelope] = []

    async def mock_emit(env: EventEnvelope) -> None:
        emitted.append(env)

    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[], emit=mock_emit)

    with patch("company.cartridges.signal.ingest.fetch_url", new=AsyncMock(return_value=_make_fetch_result(RSS_FIXTURE))):
        count1 = await cartridge.pull(context)
        count2 = await cartridge.pull(context)

    assert count1 == 3
    assert count2 == 0  # all items already seen
    assert len(emitted) == 3  # no new emissions on second pull


@pytest.mark.asyncio
async def test_pull_respects_max_items(db: EventDB) -> None:
    from company.cartridges.signal.ingest import SignalIngestCartridge

    config = SignalSourceConfig(
        sources=[SourceConfig(type=SourceType.RSS, url="https://example.com/feed.xml", label="test-feed")],
        max_items_per_pull=2,  # only allow 2 items
        ai_concurrency=3,
    )
    ai = _make_ai_client()
    signal_db = db.signal
    cartridge = SignalIngestCartridge(config=config, ai=ai, signal_db=signal_db)

    emitted: list[EventEnvelope] = []

    async def mock_emit(env: EventEnvelope) -> None:
        emitted.append(env)

    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[], emit=mock_emit)

    with patch("company.cartridges.signal.ingest.fetch_url", new=AsyncMock(return_value=_make_fetch_result(RSS_FIXTURE))):
        count = await cartridge.pull(context)

    assert count == 2
    assert len(emitted) == 2


@pytest.mark.asyncio
async def test_process_passes_through_non_trigger_event(db: EventDB, source_config: SignalSourceConfig) -> None:
    from company.cartridges.signal.ingest import SignalIngestCartridge

    ai = _make_ai_client()
    signal_db = db.signal
    cartridge = SignalIngestCartridge(config=source_config, ai=ai, signal_db=signal_db)

    env = EventEnvelope(
        event="some.other.event",
        source="test",
        level=EventLevel.OPERATIONAL,
        domain="test",
        payload={},
    )
    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[])
    result = await cartridge.process(env, context)

    assert result is env  # passed through unchanged


@pytest.mark.asyncio
async def test_process_consumes_pull_trigger(db: EventDB, source_config: SignalSourceConfig) -> None:
    from company.cartridges.signal.ingest import SignalIngestCartridge

    ai = _make_ai_client()
    signal_db = db.signal
    cartridge = SignalIngestCartridge(config=source_config, ai=ai, signal_db=signal_db)

    env = EventEnvelope(
        event="signal.pull.triggered",
        source="scheduler",
        level=EventLevel.OPERATIONAL,
        domain="signal",
        payload={},
    )
    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[])

    with patch("company.cartridges.signal.ingest.fetch_url", new=AsyncMock(return_value=_make_fetch_result(RSS_FIXTURE))):
        result = await cartridge.process(env, context)

    assert result is None  # trigger consumed


@pytest.mark.asyncio
async def test_pull_emitted_envelopes_have_idempotency_key(db: EventDB, source_config: SignalSourceConfig) -> None:
    from company.cartridges.signal.ingest import SignalIngestCartridge

    ai = _make_ai_client()
    signal_db = db.signal
    cartridge = SignalIngestCartridge(config=source_config, ai=ai, signal_db=signal_db)

    emitted: list[EventEnvelope] = []

    async def mock_emit(env: EventEnvelope) -> None:
        emitted.append(env)

    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[], emit=mock_emit)

    with patch("company.cartridges.signal.ingest.fetch_url", new=AsyncMock(return_value=_make_fetch_result(RSS_FIXTURE))):
        await cartridge.pull(context)

    assert all(env.idempotency_key is not None for env in emitted)
    # All idempotency keys must be unique
    keys = [env.idempotency_key for env in emitted]
    assert len(set(keys)) == len(keys)
