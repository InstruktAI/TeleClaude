# Demo: prepare-state-machine

## Validation

```bash
# 1. Verify PreparePhase enum has all 10 states
python -c "
from teleclaude.core.next_machine.core import PreparePhase
expected = ['input_assessment', 'triangulation', 'requirements_review',
            'plan_drafting', 'plan_review', 'gate', 'grounding_check',
            're_grounding', 'prepared', 'blocked']
actual = [p.value for p in PreparePhase]
assert actual == expected, f'Mismatch: {actual}'
print('PASS: All 10 PreparePhase states defined')
"
```

```bash
# 2. Verify hitl parameter is fully removed
! grep -r 'hitl' teleclaude/core/next_machine/core.py teleclaude/cli/tool_commands.py teleclaude/api/todo_routes.py 2>/dev/null && echo "PASS: No hitl references in production code" || echo "FAIL: hitl still referenced"
```

```bash
# 3. Verify DEFAULT_STATE includes grounding and review sections
python -c "
from teleclaude.core.next_machine.core import DEFAULT_STATE
assert 'grounding' in DEFAULT_STATE, 'Missing grounding section'
assert 'requirements_review' in DEFAULT_STATE, 'Missing requirements_review section'
assert 'plan_review' in DEFAULT_STATE, 'Missing plan_review section'
assert 'prepare_phase' in DEFAULT_STATE, 'Missing prepare_phase key'
g = DEFAULT_STATE['grounding']
assert 'valid' in g and 'base_sha' in g and 'referenced_paths' in g
print('PASS: DEFAULT_STATE extended with grounding and review sections')
"
```

```bash
# 4. Verify state backward compatibility (existing state.yaml without new sections)
python -c "
import tempfile, yaml
from pathlib import Path
from teleclaude.core.next_machine.core import read_phase_state

with tempfile.TemporaryDirectory() as tmpdir:
    slug = 'demo-slug'
    state_dir = Path(tmpdir) / 'todos' / slug
    state_dir.mkdir(parents=True)
    # Write a legacy state.yaml without new sections
    (state_dir / 'state.yaml').write_text(yaml.dump({'build': 'pending', 'review': 'pending'}))
    state = read_phase_state(tmpdir, slug)
    assert state['grounding']['valid'] is False, 'grounding.valid should default to False'
    assert state['prepare_phase'] == '', 'prepare_phase should default to empty'
    print('PASS: Legacy state.yaml loads with sensible defaults')
"
```

```bash
# 5. Verify CLI help text reflects new flags
telec todo prepare --help 2>&1 | grep -q 'invalidate-check' && echo "PASS: --invalidate-check flag in help" || echo "FAIL: Missing --invalidate-check"
telec todo prepare --help 2>&1 | grep -q 'changed-paths' && echo "PASS: --changed-paths flag in help" || echo "FAIL: Missing --changed-paths"
! telec todo prepare --help 2>&1 | grep -q 'no-hitl' && echo "PASS: --no-hitl removed from help" || echo "FAIL: --no-hitl still in help"
```

```bash
# 6. Run the unit tests for the new state machine
pytest tests/unit/test_prepare_state_machine.py tests/unit/test_next_machine_hitl.py tests/unit/test_next_machine_breakdown.py -v --tb=short 2>&1 | tail -30
```

```bash
# 7. Full test suite regression check
make test 2>&1 | tail -5
```

## Guided Presentation

### Step 1: The PreparePhase Enum

Run `python -c "from teleclaude.core.next_machine.core import PreparePhase; [print(f'  {p.value}') for p in PreparePhase]"`.

Observe: 10 states printed, matching the lifecycle from input assessment through
prepared/blocked terminal states. This is the foundation -- every phase has a
dedicated handler in the dispatch loop.

### Step 2: State Machine in Action -- Fresh Todo

Set up a fresh todo with only input.md:
```
mkdir -p /tmp/demo-psm/todos/demo-item
echo "# Build a widget" > /tmp/demo-psm/todos/demo-item/input.md
echo "- slug: demo-item" > /tmp/demo-psm/todos/roadmap.yaml
```

Call `telec todo prepare demo-item` from `/tmp/demo-psm`.

Observe: The machine detects no breakdown assessment, enters INPUT_ASSESSMENT,
and returns a `format_tool_call()` instruction dispatching `next-prepare-draft`
with a note to assess the input. No HITL guidance -- always structured tool-call
instructions.

### Step 3: State Machine Phase Progression

Write a requirements.md and set the review verdict in state.yaml:
```
echo "# Requirements" > /tmp/demo-psm/todos/demo-item/requirements.md
# Simulate reviewer writing verdict
python -c "
import yaml
from pathlib import Path
state_path = Path('/tmp/demo-psm/todos/demo-item/state.yaml')
state = yaml.safe_load(state_path.read_text()) if state_path.exists() else {}
state['breakdown'] = {'assessed': True, 'todos': []}
state['requirements_review'] = {'verdict': 'approve', 'reviewed_at': '2026-03-07T12:00:00Z', 'findings_count': 0}
state_path.write_text(yaml.dump(state, default_flow_style=False))
"
```

Call `telec todo prepare demo-item` again.

Observe: The machine reads the approved verdict, transitions through
REQUIREMENTS_REVIEW -> PLAN_DRAFTING, and dispatches `next-prepare-draft` to write
the implementation plan. The `prepare_phase` in state.yaml is updated durably at
each transition.

### Step 4: Invalidation Check

Set up grounding with referenced paths:
```
python -c "
import yaml
from pathlib import Path
state_path = Path('/tmp/demo-psm/todos/demo-item/state.yaml')
state = yaml.safe_load(state_path.read_text())
state['grounding'] = {
    'valid': True,
    'base_sha': 'abc123',
    'input_digest': 'def456',
    'referenced_paths': ['src/widget.py', 'src/utils.py'],
    'last_grounded_at': '2026-03-07T12:00:00Z',
    'invalidated_at': '',
    'invalidation_reason': '',
}
state_path.write_text(yaml.dump(state, default_flow_style=False))
"
```

Call `telec todo prepare --invalidate-check --changed-paths src/widget.py` from
`/tmp/demo-psm`.

Observe: The command detects overlap between `src/widget.py` and the referenced
paths, sets `grounding.valid = false`, and returns JSON listing `demo-item` as
invalidated. Sub-second, no agent dispatch.

### Step 5: Pre-Build Freshness Gate

With `grounding.valid = false` from the previous step, attempt a build:
call `telec todo work demo-item`.

Observe: `next_work` detects the stale grounding and returns a STALE instruction
instead of dispatching a builder. The orchestrator must run
`telec todo prepare demo-item` first to re-ground.

### Cleanup

```
rm -rf /tmp/demo-psm
```

The state machine transforms preparation from a fragile if/else chain into a
durable, crash-recoverable lifecycle with mechanical freshness enforcement. Every
call reads state, advances one step, and persists the result -- exactly matching
the integration pattern.
