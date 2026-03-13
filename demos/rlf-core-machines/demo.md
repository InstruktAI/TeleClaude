# Demo: rlf-core-machines

## Validation

Verify the structural decomposition: both large state machine files are split into
focused sub-modules under the 800-line limit, all backward-compatible imports still
resolve, and the test suite passes.

```bash
# 1. Verify core.py is now a thin re-export facade (≤ 250 lines)
lines=$(wc -l < teleclaude/core/next_machine/core.py)
echo "core.py lines: $lines"
[ "$lines" -le 250 ] || { echo "FAIL: core.py too large ($lines lines)"; exit 1; }
echo "PASS: core.py is within 250 lines"
```

```bash
# 2. Verify state_machine.py is now a slim orchestrator (≤ 300 lines)
lines=$(wc -l < teleclaude/core/integration/state_machine.py)
echo "state_machine.py lines: $lines"
[ "$lines" -le 300 ] || { echo "FAIL: state_machine.py too large ($lines lines)"; exit 1; }
echo "PASS: state_machine.py is within 300 lines"
```

```bash
# 3. Verify all new sub-modules exist and are within 800 lines each
for f in \
  teleclaude/core/next_machine/_types.py \
  teleclaude/core/next_machine/state_io.py \
  teleclaude/core/next_machine/roadmap.py \
  teleclaude/core/next_machine/icebox.py \
  teleclaude/core/next_machine/delivery.py \
  teleclaude/core/next_machine/git_ops.py \
  teleclaude/core/next_machine/slug_resolution.py \
  teleclaude/core/next_machine/output_formatting.py \
  teleclaude/core/next_machine/build_gates.py \
  teleclaude/core/next_machine/worktrees.py \
  teleclaude/core/next_machine/prepare_events.py \
  teleclaude/core/next_machine/prepare_steps.py \
  teleclaude/core/integration/checkpoint.py \
  teleclaude/core/integration/formatters.py \
  teleclaude/core/integration/step_functions.py; do
  lines=$(wc -l < "$f")
  echo "$f: $lines lines"
  [ "$lines" -le 800 ] || { echo "FAIL: $f too large ($lines lines)"; exit 1; }
done
echo "PASS: all sub-modules within 800 lines"
```

```bash
# 4. Verify backward-compatible imports from core still resolve
python -c "
from teleclaude.core.next_machine.core import (
    next_prepare, next_work, next_create,
    load_roadmap, save_roadmap,
    read_phase_state, write_phase_state,
    run_build_gates, verify_artifacts,
    ensure_worktree_with_policy,
    _emit_prepare_event,
    compose_agent_guidance,
)
print('PASS: all public imports from core resolve')
"
```

```bash
# 5. Verify integration module imports still resolve
python -c "
from teleclaude.core.integration.state_machine import next_integrate, IntegrationPhase
from teleclaude.core.integration.checkpoint import IntegrationPhase as Phase, _read_checkpoint
from teleclaude.core.integration.step_functions import _step_idle, _step_cleanup
print('PASS: integration imports resolve')
"
```

```bash
# 6. Run the test suite
make test
```

## Guided Presentation

### What was built

Two monolithic state machine files were structurally decomposed into focused sub-modules:

- `teleclaude/core/next_machine/core.py` (4,952 lines → 207 lines): now a backward-compat re-export facade pulling from 15 focused sub-modules
- `teleclaude/core/integration/state_machine.py` (~1,200 lines → 279 lines): now a slim orchestrator, with phase/checkpoint logic in `checkpoint.py` and all step functions in `step_functions.py`

No behavior was changed. All public imports continue to resolve. The test suite passes with 139 tests.

### What to observe

Run each bash block in sequence. Every block should print "PASS" and exit 0. The final block runs the full test suite — all 139 tests should pass.
