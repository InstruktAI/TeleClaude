# Demo: remove-phase-field

## Validation

<!-- Bash code blocks that prove the feature works. -->
<!-- Each block is run by `telec todo demo remove-phase-field` as a build gate — all must exit 0. -->

```bash
# Verify ItemPhase enum is removed from codebase
! grep -r "class ItemPhase" teleclaude/
```

```bash
# Verify get_item_phase / set_item_phase functions are removed
! grep -r "def get_item_phase\|def set_item_phase" teleclaude/
```

```bash
# Verify "phase" is not in DEFAULT_STATE
! grep -A1 "DEFAULT_STATE" teleclaude/core/next_machine/core.py | grep '"phase"'
```

```bash
# Verify TodoState model has no phase field
! grep 'phase.*=.*"pending"' teleclaude/types/todos.py
```

```bash
# Verify no production code imports ItemPhase, get_item_phase, or set_item_phase
! grep -r "ItemPhase\|get_item_phase\|set_item_phase" teleclaude/ --include="*.py"
```

```bash
# Tests pass
make test
```

```bash
# Lint passes
make lint
```

```bash
# Existing state.yaml files with phase field still parse without error
python3 -c "
from teleclaude.core.next_machine.core import read_phase_state
import tempfile, os, yaml
d = tempfile.mkdtemp()
slug = 'test-compat'
os.makedirs(os.path.join(d, 'todos', slug))
with open(os.path.join(d, 'todos', slug, 'state.yaml'), 'w') as f:
    yaml.dump({'phase': 'in_progress', 'build': 'started', 'review': 'pending'}, f)
state = read_phase_state(d, slug)
assert state['build'] == 'started', f'Expected started, got {state[\"build\"]}'
print('Backward compat OK')
"
```

## Guided Presentation

**Medium:** CLI / terminal

1. **Show the enum is gone.** Grep for `ItemPhase` across the codebase — zero matches in production code. The system derives lifecycle state from `build` and `review` only.

2. **Show a fresh todo scaffold.** Run `telec todo create demo-test` and inspect `state.yaml` — no `phase` field present. Only `build`, `review`, and derived fields.

3. **Show the TUI.** Open `telec` and observe the roadmap view. Items display correct status (`pending`, `ready`, `in_progress`) derived entirely from `build` + `dor.score`. No visual regression.

4. **Show backward compatibility.** Point to a state.yaml that still has a `phase` key from before the migration. It loads without error — the stale key is silently carried and ignored.

5. **Show the state machine diagram.** The diagram extractor no longer generates `ItemPhase` transitions. The `build`/`review` state machine diagram is the single source of truth.
