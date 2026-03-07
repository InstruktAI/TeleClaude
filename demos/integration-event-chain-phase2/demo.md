# Demo: integration-event-chain-phase2

## Validation

```bash
# 1. Verify branch.pushed event schema is registered
python -c "
from teleclaude_events.catalog import EventCatalog
from teleclaude_events.schemas.software_development import register_software_development

catalog = EventCatalog()
register_software_development(catalog)
schema = catalog.get('domain.software-development.branch.pushed')
assert schema is not None, 'branch.pushed schema not registered'
assert 'branch' in schema.idempotency_fields
print('PASS: branch.pushed schema registered')
"
```

```bash
# 2. Verify emit_branch_pushed exists and is callable
python -c "
from teleclaude.core.integration_bridge import emit_branch_pushed
import inspect
assert inspect.iscoroutinefunction(emit_branch_pushed), 'must be async'
print('PASS: emit_branch_pushed is async and importable')
"
```

```bash
# 3. Verify finalize lock functions are removed
python -c "
import ast

with open('teleclaude/core/next_machine/core.py') as f:
    tree = ast.parse(f.read())

fn_names = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
removed = ['acquire_finalize_lock', 'release_finalize_lock', 'get_finalize_lock_holder']
for name in removed:
    assert name not in fn_names, f'{name} still exists in core.py'
print('PASS: finalize lock functions removed')
"
```

```bash
# 4. Verify caller_session_id removed from next_work
python -c "
import ast

with open('teleclaude/core/next_machine/core.py') as f:
    tree = ast.parse(f.read())

for node in ast.walk(tree):
    if isinstance(node, ast.AsyncFunctionDef) and node.name == 'next_work':
        params = [a.arg for a in node.args.args]
        assert 'caller_session_id' not in params, 'caller_session_id still in next_work'
        print('PASS: caller_session_id removed from next_work')
        break
"
```

```bash
# 5. Verify cartridge monitors all three event types
python -c "
from teleclaude_events.cartridges.integration_trigger import INTEGRATION_EVENT_TYPES

required = {
    'domain.software-development.review.approved',
    'domain.software-development.branch.pushed',
    'domain.software-development.deployment.started',
}
assert required.issubset(INTEGRATION_EVENT_TYPES), f'Missing: {required - INTEGRATION_EVENT_TYPES}'
print('PASS: cartridge monitors all three integration event types')
"
```

```bash
# 6. Verify session cleanup does not reference finalize lock
python -c "
with open('teleclaude/core/session_cleanup.py') as f:
    content = f.read()
assert 'release_finalize_lock' not in content, 'session_cleanup still references finalize lock'
print('PASS: session cleanup clean of finalize lock references')
"
```

```bash
# 7. Full test suite
make test
```

## Guided Presentation

### Step 1: Event Schema Registration

Open `teleclaude_events/schemas/software_development.py` and observe the new `branch.pushed`
schema in the integration lifecycle section, alongside `review.approved` and
`deployment.started`. This completes the three-event contract that the readiness projection
requires.

### Step 2: Branch Push Emission

Open `teleclaude/core/integration_bridge.py` and find `emit_branch_pushed()`. This helper
follows the same pattern as `emit_review_approved()` and `emit_deployment_started()`. The
finalize worker calls it after a successful git push, feeding the `branch.pushed` signal into
the event pipeline.

### Step 3: Cartridge Wiring

Open `teleclaude_events/cartridges/integration_trigger.py`. The cartridge now monitors all
three event types. When any arrives, it maps the platform event to its canonical type and
calls the injected ingest callback. The callback feeds the event to the readiness projection
and enqueues candidates that transition to READY. Only then does the cartridge call the
spawn callback. The old `deployment.started`-only trigger is gone.

### Step 4: Legacy Removal

Show `teleclaude/core/next_machine/core.py` — `acquire_finalize_lock`,
`release_finalize_lock`, and `get_finalize_lock_holder` are gone. `next_work()` no longer
takes `caller_session_id`. The queue + readiness projection provide strictly stronger
serialization than the file-based lock ever did.

### Step 5: POST_COMPLETION Simplification

Show the rewritten `POST_COMPLETION["next-finalize"]` — it confirms FINALIZE_READY, ends the
worker, and moves on. No more `telec todo integrate` inline trigger, no more lock cleanup.
The integration is event-driven end-to-end.
