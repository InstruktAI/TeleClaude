# Demo: state-machine-core

## Validation

```bash
# Verify the state machine engine module exists and is importable
python3 -c "from teleclaude.core.next_machine.state_machine import StateMachine, TransitionDefinition; print('Engine: OK')"
```

```bash
# Verify CLI surface includes the state subcommand
telec todo state --help 2>&1 | head -5
```

```bash
# Verify a legacy v1 state auto-migrates to v2 on read
telec todo state state-machine-core 2>&1 | python3 -c "
import sys, json
data = json.load(sys.stdin)
assert data.get('current'), 'missing current field'
print(f'Migration: OK (current={data[\"current\"]})')
"
```

```bash
# Verify all tests pass
make test
```

## Guided Presentation

### Step 1: The New Primitive — State Machine Engine

The core delivery is a generic state machine engine. It manages state snapshots
through named transitions with idempotent semantics and rewind.

**Do:** Import the engine and show its interface.

```bash
python3 -c "
from teleclaude.core.next_machine.state_machine import StateMachine, TransitionDefinition, TransitionRejected, RewindRejected
print('Exports: StateMachine, TransitionDefinition, TransitionRejected, RewindRejected')
"
```

**Observe:** The module exports four symbols — the machine, the transition
definition type, and two typed exception classes.

**Why it matters:** This is the foundation for all lifecycle state management.
Every mark-* command, every phase derivation, every field-patch will eventually
route through this engine.

### Step 2: Inspect an Existing Todo's State

**Do:** Use the new `telec todo state` command to inspect a todo.

```bash
telec todo state state-machine-core
```

**Observe:** The output shows `current` (the authoritative state value),
`history` (transition log), and `valid_transitions` (what can fire next).

**Why it matters:** This replaces guessing from field combinations. One command
shows exactly where a todo is and what can happen next.

### Step 3: V1 -> V2 Auto-Migration

**Do:** Check the raw state.yaml to see v2 format after first read.

```bash
head -5 todos/state-machine-core/state.yaml
```

**Observe:** After the first read via `telec todo state`, the file has
`schema_version: 2` and a `current` field. Legacy fields like `prepare_phase`,
`build`, and `review` are gone from the migrated blob.

**Why it matters:** No manual migration step. Every v1 state file upgrades
transparently on first access.

### Step 4: Prepare Machine Routes from Authoritative State

**Do:** Run the prepare machine and observe it uses `current`, not inference.

```bash
telec todo prepare state-machine-core 2>&1 | head -10
```

**Observe:** The routing uses the `current` field directly. No
`_derive_prepare_phase` inference fallback.

**Why it matters:** The system now knows where it is because it remembers,
not because it infers.
