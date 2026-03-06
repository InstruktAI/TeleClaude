# Demo: architecture-alignment-integration-pipeline

## Validation

```bash
# 1. Verify --cwd flag works for mark-phase
telec todo mark-phase architecture-alignment-integration-pipeline --phase finalize --status complete --cwd "$(pwd)" 2>&1 | head -5
```

```bash
# 2. Verify emit_deployment_started is importable and callable
python3 -c "
from teleclaude.core.integration_bridge import emit_deployment_started
import inspect
sig = inspect.signature(emit_deployment_started)
print(f'emit_deployment_started signature: {sig}')
print('Function exists and is importable.')
"
```

```bash
# 3. Verify POST_COMPLETION guidance no longer contains direct integrate call
python3 -c "
from teleclaude.core.next_machine.core import POST_COMPLETION
guidance = POST_COMPLETION.get('next-finalize', '')
assert 'telec todo integrate' not in guidance, 'ERROR: old direct integrate call still in guidance'
assert 'mark-phase' in guidance, 'ERROR: mark-phase instruction missing from guidance'
print('POST_COMPLETION guidance updated correctly.')
"
```

```bash
# 4. Verify VCS policy reflects new commit strategy
grep -q 'commit all dirty files' docs/global/software-development/policy/version-control-safety.md && echo 'VCS policy updated.' || echo 'ERROR: VCS policy not updated.'
```

```bash
# 5. Full test suite
make test 2>&1 | tail -5
```

## Guided Presentation

### Step 1: The Enabler — mark-phase --cwd

Previously, `telec todo mark-phase` captured `os.getcwd()` with no override.
If the orchestrator ran from a different directory than the worktree, the wrong
`state.yaml` was updated. Now `--cwd` lets the orchestrator target the correct
path explicitly.

Run `telec todo mark-phase --help` to see the new `--cwd` flag.

### Step 2: The Critical Path — Post-Finalize Event Emission

The core gap: `emit_deployment_started()` existed in `integration_bridge.py` but
was never called. After a finalize worker completed, the orchestrator had to call
`telec todo integrate` directly — bypassing the event-driven architecture entirely.

Now when the orchestrator calls `telec todo work` after marking finalize complete,
`next_work()` detects the state, derives branch/sha from the worktree, and emits
the `deployment.started` event. The `IntegrationTriggerCartridge` picks it up and
spawns the integrator session automatically.

### Step 3: The Policy — State Files Commit Strategy

Workers now commit all dirty files (including `state.yaml`, `roadmap.yaml`) at
end of work. One rule instead of conditional logic. This is safe because worker
branches only reach main through the integrator — the commit trail is the audit trail.

### Step 4: What's Next

With the event-driven path wired, `next-machine-old-code-cleanup` can now strip
the old manual integration path: finalize locks, `caller_session_id` plumbing,
and the inline `telec todo integrate` call.
