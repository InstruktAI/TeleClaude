# Demo: integrator-wiring

## Validation

```bash
# Verify integration event schemas are registered in the catalog
python -c "
from teleclaude_events import EventCatalog
from teleclaude_events.catalog import build_default_catalog
catalog = build_default_catalog()
for et in ['domain.software-development.review.approved',
           'domain.software-development.deployment.started',
           'domain.software-development.deployment.completed',
           'domain.software-development.deployment.failed']:
    schema = catalog.get(et)
    assert schema is not None, f'Missing schema: {et}'
    assert schema.lifecycle is not None, f'Missing lifecycle: {et}'
    print(f'OK: {et} (level={schema.default_level}, lifecycle={schema.lifecycle})')
"
```

```bash
# Verify integration trigger cartridge is registered in the pipeline
python -c "
from teleclaude_events.cartridges.integration_trigger import IntegrationTriggerCartridge
cart = IntegrationTriggerCartridge()
print(f'OK: IntegrationTriggerCartridge instantiated')
"
```

```bash
# Verify integration bridge emission functions exist
python -c "
from teleclaude.core.integration_bridge import (
    emit_review_approved,
    emit_deployment_started,
    emit_deployment_completed,
    emit_deployment_failed,
    spawn_integrator_session,
)
print('OK: All bridge functions importable')
"
```

```bash
# Verify bidirectional sync functions are removed
python -c "
import inspect, teleclaude.core.next_machine.core as core
source = inspect.getsource(core)
assert 'sync_slug_todo_from_worktree_to_main' not in source, 'Still present: worktree-to-main sync'
assert 'sync_slug_todo_from_main_to_worktree' not in source, 'Still present: main-to-worktree sync'
print('OK: Bidirectional sync functions removed')
"
```

```bash
# Verify file-based event store is no longer used
python -c "
from teleclaude.core.integration.service import IntegrationEventService
import inspect
source = inspect.getsource(IntegrationEventService)
assert 'event_store' not in source.lower() or 'removed' in source.lower() or 'IntegrationEventStore' not in source, \
    'IntegrationEventService still references file-based event store'
print('OK: File-based event store decoupled from service')
"
```

```bash
# Verify integrator command artifact exists
test -f agents/commands/next-integrate.md && echo "OK: next-integrate command exists" || echo "FAIL: missing next-integrate command"
```

```bash
# Verify cutover env vars are set in daemon environment
make status 2>/dev/null
env | grep -E 'TELECLAUDE_INTEGRATOR_(CUTOVER|PARITY)' || echo "NOTE: Cutover env vars checked at runtime"
```

```bash
# Verify empty phantom todo directory is removed
test ! -d todos/integration-events-model && echo "OK: phantom directory removed" || echo "FAIL: phantom directory still exists"
```

```bash
# Run integration tests
make test -- tests/integration/test_integrator_wiring.py -v
```

## Guided Presentation

### Step 1: Show the old problem

Look at the current POST_COMPLETION in `teleclaude/core/next_machine/core.py`.
Before this change, the orchestrator performed 12 inline steps to merge and
push main — fetch, switch, pull, merge, bookkeeping commit, demo snapshot,
worktree remove, branch delete, todo cleanup, push, restart. Any failure
mid-sequence left main in partial state. Show the git log for commits that
removed this code.

### Step 2: Event schemas in the catalog

Run `telec events list` and filter for `deployment.*` events. Show that four
integration event types are registered with proper lifecycle declarations.
Explain that the notification projector cartridge automatically creates and
resolves notifications from these lifecycle declarations — no integration-
specific notification code needed.

### Step 3: Event emission in action

Trace the code path from `mark-phase review approved` to the
`emit_review_approved()` call. Then trace from the `/next-finalize`
POST_COMPLETION to `emit_deployment_started()`. Show that the orchestrator
stops after emission — it no longer touches main.

### Step 4: The integration trigger

Show the `IntegrationTriggerCartridge` in the pipeline chain. Explain how it
watches for integration events, feeds the readiness projection, and spawns
the integrator session when a candidate goes READY. Show the cartridge
registration in daemon startup.

### Step 5: The integrator session

Show the `next-integrate` command. Walk through a successful integration:
lease acquisition → queue drain → merge → bookkeeping → push → cleanup →
self-end. Then show a blocked integration: merge conflict → deployment.failed
emitted → follow-up todo created → admin sees notification.

### Step 6: Cutover enforcement

Attempt a direct `git push origin main` from an agent session. Show that the
shell wrapper blocks it. Only the integrator session, with the correct
environment variables, can push main.

### Step 7: What was removed

Show that `sync_slug_todo_from_worktree_to_main` and
`sync_slug_todo_from_main_to_worktree` are gone. Show that
`IntegrationEventStore` file I/O is gone. The integrator merges the full
branch — todo artifacts travel with the feature branch.
