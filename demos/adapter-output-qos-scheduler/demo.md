# Demo: adapter-output-qos-scheduler

## What was built

An adapter-level output QoS system that prevents Telegram flood-control churn under high
concurrency. Key deliverables:

- **OutputQoSScheduler**: per-adapter background scheduler with latest-only coalescing and
  round-robin fairness dispatch.
- **PTB AIORateLimiter**: transport-layer rate limiting wired into Telegram startup.
- **Telegram strict mode**: coalesces and paces output under the configured group MPM budget.
- **Discord coalesce_only mode**: drops stale intermediate payloads without hard rate caps.
- **WhatsApp stub**: off by default, ready for future enablement.

## Verification steps

### 1. Unit tests pass

```bash
.venv/bin/python -m pytest tests/unit/test_output_qos_scheduler.py -v
```

Expected: 29 tests pass covering cadence math, coalescing, fairness, priority queue, EMA, and
lifecycle.

### 2. Lint passes

```bash
make lint
```

Expected: `✓ Lint checks passed`

### 3. Full test suite

```bash
make test
```

Expected: all tests pass (pre-existing flaky timeout in test_discord_adapter is unrelated to
this change).

### 4. Config parsing validation

```bash
.venv/bin/python -c "
import os; os.environ['TELECLAUDE_CONFIG_PATH'] = 'tests/integration/config.yml'
from teleclaude.config import config
qos = config.telegram.qos
print('Telegram QoS:', qos)
assert qos.group_mpm == 20
assert qos.output_budget_ratio == 0.8
assert qos.reserve_mpm == 4
print('Discord QoS mode:', config.discord.qos.mode)
print('Config parsing: OK')
"
```

### 5. Scheduler instantiation and cadence math

```bash
.venv/bin/python -c "
import os; os.environ['TELECLAUDE_CONFIG_PATH'] = 'tests/integration/config.yml'
from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler
from teleclaude.adapters.qos.policy import QoSPolicy

policy = QoSPolicy(
    adapter_key='demo',
    mode='strict',
    group_mpm=20,
    output_budget_ratio=0.8,
    reserve_mpm=4,
    rounding_ms=100,
)
sched = OutputQoSScheduler(policy)
tick = sched._compute_tick_s()
# effective_mpm = min(20-4, floor(20*0.8)) = min(16, 16) = 16
# global_tick_s = ceil_to_100ms(60/16=3.75) = 3.8
assert abs(tick - 3.8) < 0.001, f'Expected 3.8, got {tick}'
print(f'Computed tick: {tick:.2f}s — OK')
print('Effective output budget: 16 mpm at group_mpm=20, reserve=4, ratio=0.8')
"
```

### 6. Coalescing behavior

```bash
.venv/bin/python -c "
import asyncio, os; os.environ['TELECLAUDE_CONFIG_PATH'] = 'tests/integration/config.yml'
from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler
from teleclaude.adapters.qos.policy import QoSPolicy

policy = QoSPolicy(adapter_key='demo', mode='strict', group_mpm=20, output_budget_ratio=0.8,
                   reserve_mpm=4, rounding_ms=100)
sched = OutputQoSScheduler(policy)

dispatched = []

async def f1(): dispatched.append('f1')
async def f2(): dispatched.append('f2')
async def f3(): dispatched.append('f3')

sched.enqueue('sess-a', f1)
sched.enqueue('sess-a', f2)  # supersedes f1
sched.enqueue('sess-a', f3)  # supersedes f2

assert sched._coalesced == 2, f'Expected 2 coalesced, got {sched._coalesced}'
assert sched._normal_slots['sess-a'].factory is f3, 'Latest factory should be f3'

asyncio.run(sched._dispatch_one())
assert dispatched == ['f3'], f'Expected [f3], got {dispatched}'
print(f'Coalescing OK: 2 superseded, 1 dispatched (f3)')
"
```

## Notes

- Demo steps 5 and 6 are self-contained unit-style assertions runnable in the worktree.
- Runtime validation (make restart, log grep for QoS summary) requires a live daemon and is
  validated post-merge on the main deployment.
- Tasks 5.2 (integration load test) and 5.3 (runtime log validation) are deferred to
  post-merge monitoring per the build plan scope.
