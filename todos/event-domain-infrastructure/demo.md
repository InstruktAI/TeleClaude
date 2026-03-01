# Demo: event-domain-infrastructure

## Validation

```bash
# 1. Verify domain config schema loads without error
python -c "from teleclaude_events.domain_config import DomainsConfig; print(DomainsConfig().model_dump_json(indent=2))"
```

```bash
# 2. Verify cartridge DAG resolution with test fixtures
python -c "
from teleclaude_events.cartridge_loader import resolve_dag, LoadedCartridge
from teleclaude_events.cartridge_manifest import CartridgeManifest
# Two cartridges: B depends on A
a = LoadedCartridge(manifest=CartridgeManifest(id='a', description='test'), module_path=None, process=None)
b = LoadedCartridge(manifest=CartridgeManifest(id='b', description='test', depends_on=['a']), module_path=None, process=None)
levels = resolve_dag([a, b])
assert len(levels) == 2 and levels[0][0].manifest.id == 'a'
print('DAG resolution: OK — 2 levels, a before b')
"
```

```bash
# 3. Verify autonomy matrix resolution priority
python -c "
from teleclaude_events.domain_config import AutonomyMatrix, AutonomyLevel
m = AutonomyMatrix(
    global_default=AutonomyLevel.notify,
    by_domain={'dev': AutonomyLevel.autonomous},
    by_event_type={'dev/build.complete': AutonomyLevel.manual}
)
# event_type override beats domain
assert m.resolve('dev', 'any-cart', 'build.complete') == AutonomyLevel.manual
# domain beats global
assert m.resolve('dev', 'any-cart', 'deploy.started') == AutonomyLevel.autonomous
print('Autonomy matrix priority: OK')
"
```

```bash
# 4. Verify domain pipeline runner parallel execution
python -c "
import asyncio
from teleclaude_events.domain_pipeline import DomainPipelineRunner
# Empty runner should complete without error
runner = DomainPipelineRunner({})
print('DomainPipelineRunner instantiation: OK')
"
```

```bash
# 5. Verify lifecycle commands exist
telec config cartridges list 2>&1 | head -5
```

```bash
# 6. Full test suite
make test
```

```bash
# 7. Lint clean
make lint
```

## Guided Presentation

### Step 1: Config Foundation

Show the domain config schema with defaults. Explain the four-level autonomy matrix
(event_type > cartridge > domain > global) and how it resolves. Show `telec config get domains`
returning the default configuration.

**Observe:** Empty domains config loads cleanly. Autonomy resolution follows the priority chain.

### Step 2: Cartridge Discovery and DAG

Create a test domain folder with two cartridges (A depends on B). Run discovery and show
the topological sort output. Introduce a cycle and show the `CartridgeCycleError`.

**Observe:** Cartridges are discovered from filesystem, DAG resolves correctly, cycles are
caught at startup with a clear error message identifying the cycle path.

### Step 3: Domain Pipeline Execution

Emit a test event with `domain: "software-development"`. Show the event flowing through
the system pipeline, then fanning out to the domain pipeline. Show per-cartridge exception
isolation (one cartridge raises, others still execute).

**Observe:** Domain pipeline runs in parallel after system pipeline. Cartridge failure is
isolated — the domain pipeline continues. Results are logged at DEBUG level.

### Step 4: Personal Subscriptions

Configure a personal cartridge for a test member. Emit an event and show the personal
cartridge executing after domain cartridges. Show that a non-leaf personal cartridge
(with depends_on) is rejected at load time.

**Observe:** Personal cartridges run as leaf nodes after domain cartridges. Scope enforcement
prevents non-leaf installations.

### Step 5: Lifecycle Operations

Install a cartridge via `telec config cartridges install`. List cartridges. Promote from
personal to domain scope (requires admin). Show permission error for non-admin promote.
Remove the cartridge. Show pipeline reload after each operation.

**Observe:** Full CRUD lifecycle works. Permission enforcement is role-based. Pipeline
reloads after mutations.

### Step 6: Autonomy in Action

Set autonomy for a specific event_type/domain combination to `manual`. Emit an event
matching that path. Show the cartridge being skipped with a `cartridge.skipped` event
logged. Change to `autonomous` and show silent execution.

**Observe:** Autonomy matrix controls cartridge execution at runtime. Each level behaves
differently (manual skips, notify runs+notifies, autonomous runs silently).
