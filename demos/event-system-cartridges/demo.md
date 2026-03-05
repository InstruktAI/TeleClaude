# Demo: event-system-cartridges

## Validation

Verify all four cartridges can be imported from the public API:

```bash
.venv/bin/python -c "from teleclaude_events.cartridges import TrustCartridge, EnrichmentCartridge, CorrelationCartridge, ClassificationCartridge; print('All four cartridges importable')"
```

Verify pipeline context accepts new fields without breaking existing callsites:

```bash
.venv/bin/python -c "
from teleclaude_events.pipeline import PipelineContext
from teleclaude_events.catalog import EventCatalog
from teleclaude_events.db import EventDB
import asyncio, tempfile, os

async def check():
    with tempfile.TemporaryDirectory() as tmp:
        db = EventDB(db_path=os.path.join(tmp, 'test.db'))
        await db.init()
        ctx = PipelineContext(catalog=EventCatalog(), db=db)
        assert hasattr(ctx, 'trust_config')
        assert hasattr(ctx, 'correlation_config')
        assert ctx.producer is None
        await db.close()
        print('PipelineContext extensions OK')

asyncio.run(check())
"
```

Verify quarantine table is created and writable:

```bash
.venv/bin/python -c "
import asyncio, tempfile, os
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope, EventLevel

async def check():
    with tempfile.TemporaryDirectory() as tmp:
        db = EventDB(db_path=os.path.join(tmp, 'test.db'))
        await db.init()
        env = EventEnvelope(event='test.event', source='intruder', level=EventLevel.WORKFLOW)
        row_id = await db.quarantine_event(env, ['unknown_source'])
        assert row_id > 0
        rows = await db.list_quarantined()
        assert len(rows) == 1
        await db.close()
        print('Quarantine table OK, row_id:', row_id)

asyncio.run(check())
"
```

Verify correlation window table is created and queryable:

```bash
.venv/bin/python -c "
import asyncio, tempfile, os
from datetime import datetime, timedelta
from teleclaude_events.db import EventDB

async def check():
    with tempfile.TemporaryDirectory() as tmp:
        db = EventDB(db_path=os.path.join(tmp, 'test.db'))
        await db.init()
        now = datetime.utcnow()
        await db.increment_correlation_window('test.event', None, now)
        count = await db.get_correlation_count('test.event', None, now - timedelta(seconds=300))
        assert count == 1
        await db.close()
        print('Correlation window table OK, count:', count)

asyncio.run(check())
"
```

Run the full cartridge unit test suite:

```bash
.venv/bin/pytest tests/unit/test_teleclaude_events/ --override-ini="addopts=-v --strict-markers --strict-config --tb=short" -q 2>&1 | tail -5
```

## Guided Presentation

### What was built

Four intelligence cartridges now slot into the event pipeline before the notification projector. Every event flowing through TeleClaude's system pipeline is now:

1. **Trust-evaluated** — events from unknown sources are flagged, quarantined, or rejected based on strictness configuration
2. **Enriched** — events with recognized entity URIs (`telec://todo/*`, `telec://worker/*`) get platform context appended to their payload
3. **Correlated** — burst detection, failure cascade detection, and entity degradation patterns emit synthetic events back into the pipeline
4. **Classified** — events are annotated with `_classification: {treatment, actionable}` so downstream cartridges (like the notification projector) can fast-path signal-only events

The pipeline order is now: `trust → dedup → enrichment → correlation → classification → [domain cartridges] → notification projector → prepare quality`

### Observing the cartridges

1. Observe the import surface: `from teleclaude_events.cartridges import TrustCartridge, EnrichmentCartridge, CorrelationCartridge, ClassificationCartridge`
2. Run the new unit tests to see each cartridge's behavior in isolation: `pytest tests/unit/test_teleclaude_events/test_cartridge_*.py -v`
3. Run the integration tests to see the full pipeline: `pytest tests/unit/test_teleclaude_events/test_pipeline_integration.py -v`
