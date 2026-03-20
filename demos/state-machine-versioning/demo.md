# Demo: state-machine-versioning

## Medium

CLI — all demonstrations use `telec` commands and state.yaml inspection.

## Scenarios

### 1. State inspection

```bash
# Show current state, history, and valid transitions for a todo
telec todo state <slug>
```

**Expected:** JSON output showing `current`, `history` array, and list of valid
transitions from the current state.

### 2. Fire a transition

```bash
# Advance a todo through a named transition
telec todo state <slug> approve_requirements
```

**Expected:** JSON output with `current` updated to the target state. History array
contains a new entry with source, target, transition name, timestamp, and actor.

### 3. Idempotent transition (already past)

```bash
# Fire a transition the todo has already passed
telec todo state <slug> approve_requirements
```

**Expected:** No-op. `current` unchanged, history unchanged, no error.

### 4. Rewind

```bash
# Pop to previous state
telec todo state <slug> --rewind
```

**Expected:** `current` restored to the previous state. Last history entry removed.

### 5. V1 → V2 migration transparency

```bash
# Inspect a todo that still has v1 state.yaml on disk
cat todos/<slug>/state.yaml  # shows schema_version: 1, prepare_phase, build, review
telec todo state <slug>       # returns v2 format with current derived from legacy fields
```

**Expected:** The API returns v2 format transparently. `current` is derived from the
v1 field combination. Legacy fields (`build`, `review`, `prepare_phase`) are absent
from the response.

### 6. Prepare machine routing from current

```bash
# Run prepare and observe it routes from current, not prepare_phase
telec todo prepare <slug>
```

**Expected:** Prepare machine reads `state["current"]` and dispatches to the correct
step. No `_derive_prepare_phase` fallback in logs.

### 7. Mark-\* backward compatibility

```bash
# Existing mark-phase command still works (wraps engine transition)
telec todo mark-phase <slug> --phase build --status started
telec todo state <slug>  # shows current=build_started with history entry
```

**Expected:** Mark-\* commands produce the same observable state changes, now with
history entries recorded.

## Validation commands

```bash
# Verify no inference-based state reads remain
grep -rn 'state\["build"\]\|state\["review"\]\|state\["prepare_phase"\]' teleclaude/ \
  --include='*.py' | grep -v migration | grep -v test

# Verify pre-commit hooks pass
git add -A && git commit --dry-run

# Verify test specs are GREEN (no longer xfail)
python -m pytest tests/unit/core/next_machine/test_state_machine_engine_specs.py -v
python -m pytest tests/unit/core/next_machine/test_state_machine_versioning_specs.py -v
python -m pytest tests/unit/cli/tool_commands/test_todo_state_specs.py -v
python -m pytest tests/unit/cli/telec/test_todo_state_surface_specs.py -v
```
