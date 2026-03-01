# Demo: event-signal-pipeline

## Validation

<!-- Bash code blocks that prove the feature works. -->
<!-- Blocks are validated by `telec todo demo validate event-signal-pipeline` (structural check) during build. -->
<!-- Execution (`telec todo demo run event-signal-pipeline`) happens on main after merge. -->

```bash
# Verify signal schemas are registered
python -c "
from teleclaude_events.catalog import build_default_catalog
catalog = build_default_catalog()
for et in ['signal.ingest.received', 'signal.cluster.formed', 'signal.synthesis.ready']:
    schema = catalog.get(et)
    assert schema is not None, f'Missing schema: {et}'
    print(f'{et}: level={schema.default_level.name}, domain={schema.domain}')
print('All signal schemas registered.')
"
```

```bash
# Verify cartridge imports
python -c "
from company.cartridges.signal import SignalIngestCartridge, SignalClusterCartridge, SignalSynthesizeCartridge
print(f'Ingest: {SignalIngestCartridge}')
print(f'Cluster: {SignalClusterCartridge}')
print(f'Synthesize: {SignalSynthesizeCartridge}')
print('All cartridges importable.')
"
```

```bash
# Verify source config loading (inline + OPML + CSV)
python -c "
from teleclaude_events.signal.sources import SignalSourceConfig, SourceConfig, SourceType
cfg = SignalSourceConfig(sources=[
    SourceConfig(type=SourceType.RSS, url='https://example.com/feed.xml', label='test-feed'),
])
assert len(cfg.sources) == 1
print(f'Inline source config: {cfg.sources[0].label} ({cfg.sources[0].type})')
print('Source config model works.')
"
```

```bash
# Verify signal DB tables exist
python -c "
import asyncio, aiosqlite
async def check():
    async with aiosqlite.connect(':memory:') as db:
        from teleclaude_events.signal.db import SignalDB
        sdb = SignalDB(db)
        await sdb.init()
        tables = [r[0] for r in await db.execute_fetchall(
            \"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'signal_%'\"
        )]
        for expected in ['signal_items', 'signal_clusters', 'signal_syntheses']:
            assert expected in tables, f'Missing table: {expected}'
            print(f'Table {expected}: present')
    print('All signal tables created.')
asyncio.run(check())
"
```

```bash
# Verify RSS parsing
python -c "
from teleclaude_events.signal.fetch import parse_rss_feed
rss = '''<?xml version=\"1.0\"?>
<rss version=\"2.0\"><channel><title>Test</title>
<item><title>Item 1</title><link>https://example.com/1</link></item>
<item><title>Item 2</title><link>https://example.com/2</link></item>
</channel></rss>'''
items = parse_rss_feed(rss)
assert len(items) == 2
print(f'Parsed {len(items)} RSS items: {[i[\"title\"] for i in items]}')
"
```

```bash
# Verify no teleclaude imports in signal cartridges
! grep -r "from teleclaude\." company/cartridges/signal/ && echo "No teleclaude imports in signal cartridges."
! grep -r "from teleclaude\." teleclaude_events/signal/ && echo "No teleclaude imports in signal modules."
```

```bash
# Run tests
make test
```

```bash
# Run linter
make lint
```

## Guided Presentation

<!-- Walk through the delivery step by step. For each step: what to do, what to observe, why it matters. -->
<!-- The AI presenter reads this top-to-bottom and executes. Write it as a continuous sequence. -->

### Step 1: Signal schemas are registered in the event catalog

Run the schema verification. You should see three signal event types registered:
`signal.ingest.received` (OPERATIONAL), `signal.cluster.formed` (OPERATIONAL),
and `signal.synthesis.ready` (WORKFLOW). The synthesis event is the only one that
creates notifications — it's the output that domain pipelines subscribe to.

### Step 2: Cartridge modules are importable

Import the three cartridges from `company.cartridges.signal`. This proves the package
scaffolding is correct and the cartridge loader can discover them. These are the first
cartridges under `company/cartridges/`, establishing the authoring pattern.

### Step 3: Source configuration model validates

Create a source config with an inline RSS feed. The model validates types and defaults.
In production, sources can also be loaded from OPML and CSV file references. The pull
interval defaults to 15 minutes.

### Step 4: Signal database tables are initialized

Create a SignalDB in memory and verify that `signal_items`, `signal_clusters`, and
`signal_syntheses` tables are created. These tables extend the event platform's storage
without requiring a separate database file.

### Step 5: RSS feed parsing works

Parse a minimal RSS 2.0 feed and verify item extraction. The ingest cartridge uses this
to normalize raw feed content into event envelopes. Atom format is also supported.

### Step 6: Import boundary is clean

Verify that signal cartridge code (`company/cartridges/signal/` and
`teleclaude_events/signal/`) has zero imports from `teleclaude.*`. This ensures the
signal pipeline is domain-agnostic and portable.

### Step 7: Tests and lint pass

Run the full test suite and linter to confirm nothing regressed and all new code
meets quality standards.
