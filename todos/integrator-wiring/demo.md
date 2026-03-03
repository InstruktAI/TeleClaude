# Demo: integrator-wiring

## Validation

```bash
# Verify integration event schemas are registered in the catalog (5 schemas)
python -c "
from teleclaude_events import EventCatalog
from teleclaude_events.catalog import build_default_catalog
catalog = build_default_catalog()
for et in ['domain.software-development.review.approved',
           'domain.software-development.deployment.started',
           'domain.software-development.branch.pushed',
           'domain.software-development.deployment.completed',
           'domain.software-development.deployment.failed']:
    schema = catalog.get(et)
    assert schema is not None, f'Missing schema: {et}'
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
# Verify integration bridge emission functions exist (including branch_pushed)
python -c "
from teleclaude.core.integration_bridge import (
    emit_review_approved,
    emit_branch_pushed,
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
# Verify finalize lock functions are removed
python -c "
import inspect, teleclaude.core.next_machine.core as core
source = inspect.getsource(core)
assert 'acquire_finalize_lock' not in source, 'Still present: acquire_finalize_lock'
assert 'release_finalize_lock' not in source, 'Still present: release_finalize_lock'
assert 'get_finalize_lock_holder' not in source, 'Still present: get_finalize_lock_holder'
print('OK: Finalize lock functions removed')
"
```

```bash
# Verify next_work has no lock parameters and requires slug
python -c "
import inspect, teleclaude.core.next_machine.core as core
sig = inspect.signature(core.next_work)
params = list(sig.parameters.keys())
assert 'caller_session_id' not in params, 'Still present: caller_session_id parameter'
print(f'OK: next_work signature: {sig}')
"
```

```bash
# Verify file-based event store is no longer used by the service
python -c "
from teleclaude.core.integration.service import IntegrationEventService
import inspect
source = inspect.getsource(IntegrationEventService)
assert 'IntegrationEventStore' not in source, \
    'IntegrationEventService still references file-based event store'
print('OK: File-based event store decoupled from service')
"
```

```bash
# Verify integrator command artifact exists
test -f agents/commands/next-integrate.md && echo "OK: next-integrate command exists" || echo "FAIL: missing next-integrate command"
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

### Act 1: The Old World (Show the Problem)

Look at git history for the removed POST_COMPLETION in
`teleclaude/core/next_machine/core.py`. Before this change, the orchestrator
performed 12 inline steps to merge and push main — on canonical main, in the
project root, with a file-based lock. Show the three chronic problems:
bidirectional sync causing state.yaml drift, inline merge leaving main in
partial state on failure, file-based finalize lock as a fragile band-aid for
serialization.

### Act 2: The Event Bridge (Schemas + Emission)

Run `telec events list` and filter for integration events. Show that five
event types are registered — including `branch.pushed` as a separate event
(required by the readiness projection's three-event predicate). Trace the code
path from `mark-phase review approved` to `emit_review_approved()`, and from
the `/next-finalize` POST_COMPLETION to `emit_deployment_started()`. Show
that the orchestrator stops after emission — it no longer touches main.

### Act 3: The Trigger (Pipeline → Integrator)

Show the `IntegrationTriggerCartridge` in the pipeline chain. Walk through how
it translates `EventEnvelope` to `IntegrationEvent` (three type mappings:
`review.approved` → `review_approved`, `deployment.started` → `finalize_ready`,
`branch.pushed` → `branch_pushed`), feeds the readiness projection, and spawns
the integrator when a candidate goes READY. Show the cartridge registration in
daemon startup.

### Act 4: The Integrator (Sole Gatekeeper)

Show the `next-integrate` command. Walk through a successful integration:
lease acquisition → queue drain → merge → bookkeeping → push → cleanup →
self-end. Then show a blocked integration: merge conflict → deployment.failed
emitted → follow-up todo created → admin sees notification. Attempt a direct
`git push origin main` from an agent session — show the shell wrapper blocks
it. Only the integrator can push main.

### Act 5: The New World (Three-Actor Architecture)

Show the architecture in action: daemon routes events through the pipeline,
per-slug orchestrator operates from its worktree (`subfolder=trees/{slug}`),
integrator owns main exclusively.

Demonstrate that `next_work(slug)` is now single-slug — no cross-slug loop.
Show that the finalize lock, bidirectional sync, and file-based event store
are gone. Show the orchestrator dispatch with `subfolder=trees/{slug}` and
`project=<canonical root>`.

Celebrate: main is sacred, orchestrators are autonomous in their worktrees,
the integrator is the sole gatekeeper. The twelve-step inline merge is dead.
The file-based finalize lock is dead. Bidirectional sync is dead. Each slug
gets its own orchestrator that lives and dies in its own worktree. The event
pipeline connects them all.
