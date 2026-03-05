# Demo: event-envelope-schema

## Validation

```bash
# 1. Verify core taxonomy is registered
python -c "
from teleclaude_events.catalog import build_default_catalog
catalog = build_default_catalog()
families = set()
for schema in catalog.list_all():
    families.add(schema.event_type.split('.')[0])
print('Registered families:', sorted(families))
assert 'node' in families, 'node family missing'
assert 'deployment' in families, 'deployment family missing'
assert 'content' in families, 'content family missing'
assert 'notification' in families, 'notification family missing'
assert 'schema' in families, 'schema family missing'
print('All core families registered.')
"
```

```bash
# 2. Verify expansion joint (extra fields round-trip)
python -c "
from teleclaude_events.envelope import EventEnvelope, EventLevel
env = EventEnvelope(
    event='deployment.failed',
    source='demo',
    level=EventLevel.BUSINESS,
    domain='infrastructure',
    payload={'service': 'proxy'},
    custom_tag='mesh-origin-xyz',
    priority_override=5,
)
stream = env.to_stream_dict()
restored = EventEnvelope.from_stream_dict(stream)
assert restored.custom_tag == 'mesh-origin-xyz', 'extra field lost'
assert restored.priority_override == 5, 'extra field lost'
print('Expansion joint: extra fields survive round-trip.')
"
```

```bash
# 3. Verify JSON Schema export
python -m teleclaude_events.schema_export /tmp/envelope-schema.json
python -c "
import json
with open('/tmp/envelope-schema.json') as f:
    schema = json.load(f)
assert schema.get('title') or schema.get('properties'), 'Invalid schema'
assert 'event' in schema.get('properties', {}), 'Missing event property'
print('JSON Schema exported and valid.')
"
```

```bash
# 4. Verify schema versioning
python -c "
from teleclaude_events.envelope import SCHEMA_VERSION, EventEnvelope, EventLevel
env = EventEnvelope(event='test', source='demo', level=EventLevel.OPERATIONAL)
assert env.version == SCHEMA_VERSION, f'version mismatch: {env.version} != {SCHEMA_VERSION}'
print(f'Schema version: {SCHEMA_VERSION}')
"
```

## Guided Presentation

### Step 1: The Envelope

Show the five-layer structure by constructing a real envelope with all layers populated.
Observe that each layer has a clear purpose: identity (who), semantic (why), data (what),
affordances (what next), resolution (what done). The model validates all fields.

### Step 2: The Expansion Joint

Construct an envelope with an extra field not in the schema (`custom_tag`). Serialize it
to a Redis stream dict and back. The extra field survives. This is the mechanism for
organic schema evolution — nodes can add fields without breaking the schema, and useful
fields get promoted through governance.

### Step 3: The Core Taxonomy

List all registered event types from the catalog. Show the root families: `system`,
`domain`, `node`, `deployment`, `content`, `notification`, `schema`. Each family has
default levels, domains, and visibility tiers appropriate for its purpose.

### Step 4: JSON Schema for External Consumers

Export the JSON Schema and show it validates a real envelope. External mesh participants
and tooling can use this schema without importing Python code. The schema is versioned
by `SCHEMA_VERSION` and regenerated on each release.
