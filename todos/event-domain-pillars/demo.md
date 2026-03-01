# Demo: event-domain-pillars

## Validation

```bash
# Verify all domain schema modules register without error
python -c "
from teleclaude_events.catalog import build_default_catalog
catalog = build_default_catalog()
events = catalog.list_all()
domains = set(e.domain for e in events)
print(f'Total events: {len(events)}')
print(f'Domains: {sorted(domains)}')
assert 'software-development' in domains, 'Missing software-development domain'
assert 'marketing' in domains, 'Missing marketing domain'
assert 'creative-production' in domains, 'Missing creative-production domain'
assert 'customer-relations' in domains, 'Missing customer-relations domain'
print('All four domain pillars registered.')
"
```

```bash
# Verify existing software-development events are preserved
python -c "
from teleclaude_events.catalog import build_default_catalog
catalog = build_default_catalog()
original_events = [
    'domain.software-development.planning.todo_created',
    'domain.software-development.planning.dor_assessed',
    'domain.software-development.build.completed',
    'domain.software-development.review.verdict_ready',
]
for et in original_events:
    assert catalog.get(et) is not None, f'Missing original event: {et}'
print(f'All {len(original_events)} original events preserved.')
"
```

```bash
# Verify new software-development events were added
python -c "
from teleclaude_events.catalog import build_default_catalog
catalog = build_default_catalog()
new_events = [
    'domain.software-development.deploy.triggered',
    'domain.software-development.deploy.succeeded',
    'domain.software-development.deploy.failed',
    'domain.software-development.ops.alert_fired',
    'domain.software-development.ops.alert_resolved',
    'domain.software-development.maintenance.dependency_update',
    'domain.software-development.maintenance.security_patch',
]
for et in new_events:
    assert catalog.get(et) is not None, f'Missing new event: {et}'
print(f'All {len(new_events)} new software-development events registered.')
"
```

```bash
# Verify customer-relations events are actionable where expected
python -c "
from teleclaude_events.catalog import build_default_catalog
catalog = build_default_catalog()
actionable = [
    'domain.customer-relations.helpdesk.ticket_escalated',
    'domain.customer-relations.escalation.triggered',
]
for et in actionable:
    schema = catalog.get(et)
    assert schema is not None, f'Missing event: {et}'
    assert schema.actionable, f'Event should be actionable: {et}'
print('Customer-relations actionable events verified.')
"
```

```bash
# Verify naming convention consistency
python -c "
from teleclaude_events.catalog import build_default_catalog
catalog = build_default_catalog()
for schema in catalog.list_all():
    parts = schema.event_type.split('.')
    assert len(parts) >= 4, f'Event type too short: {schema.event_type}'
    assert parts[0] == 'domain' or parts[0] in ('signal', 'system'), \
        f'Unexpected prefix: {schema.event_type}'
print('Naming convention check passed.')
"
```

## Guided Presentation

### Step 1: Show the event catalog growth

Run the first validation block. Observe that the catalog now spans four business domains
plus the existing system events. The total count should be significantly higher than the
original 9 software-development + system events.

### Step 2: Backward compatibility proof

Run the second validation block. This proves that the existing 9 software-development
events (used by the todo lifecycle, build, and review workflows) are untouched. No
existing emitters break.

### Step 3: Software development extensions

Run the third validation block. These are the new deploy, ops, and maintenance events
that complete the software development lifecycle coverage.

### Step 4: Customer relations trust model

Run the fourth validation block. Customer-relations is the jailed domain — escalation
events are marked actionable, meaning they always surface for human review. This is the
trust boundary in action.

### Step 5: Cartridge manifests (if infrastructure is available)

Navigate to `~/.teleclaude/company/domains/` and list the four pillar directories. Each
contains a `cartridges/` subdirectory with starter cartridges. Inspect one manifest:

```bash
cat ~/.teleclaude/company/domains/software-development/cartridges/todo-lifecycle/manifest.yaml
```

Observe: `domain_affinity`, `depends_on`, explicit `event_types` list — no wildcards.

### Step 6: Domain config seeding

Run `telec config get event_domains` and observe that all four pillars are configured with
guardian settings. Note `customer-relations` has `trust_threshold: strict`.
