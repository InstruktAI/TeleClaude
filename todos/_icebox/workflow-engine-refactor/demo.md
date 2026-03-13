# Demo: workflow-engine-refactor

## Validation

```bash
# Behavioral equivalence — prepare machine
pytest tests/unit/core/next_machine/test_prepare_equivalence.py -v
```

```bash
# Behavioral equivalence — work machine
pytest tests/unit/core/next_machine/test_work_equivalence.py -v
```

```bash
# Engine unit tests — YAML loading, step resolution, language baselines
pytest tests/unit/core/next_machine/test_workflow_engine.py -v
```

```bash
# Full test suite — no regressions
make test
```

```bash
# Linting and type checking
make lint
```

```bash
# Workflow definitions are valid YAML and load into typed dataclasses
python -c "
from teleclaude.core.next_machine.engine import load_workflow
from pathlib import Path
p = load_workflow(Path('workflows/prepare.yaml'))
w = load_workflow(Path('workflows/work.yaml'))
print(f'prepare: {len(p.steps)} steps — {p.name}')
print(f'work: {len(w.steps)} steps — {w.name}')
for step in p.steps:
    cmd = step.producer.command if step.producer else '(mechanical)'
    print(f'  prepare.{step.name}: command={cmd}, state_key={step.state_key}')
for step in w.steps:
    cmd = step.producer.command if step.producer else '(mechanical)'
    alts = step.producer.alt_commands if step.producer else {}
    vals = step.validators
    print(f'  work.{step.name}: command={cmd}, alt_commands={alts}, validators={vals}')
"
```

```bash
# State compatibility — existing state.yaml reads correctly through engine
python -c "
from teleclaude.core.next_machine.core import read_phase_state
state = read_phase_state('.', 'workflow-engine-refactor')
print(f'prepare_phase: {state.get(\"prepare_phase\")}')
print(f'build: {state.get(\"build\")}')
print(f'review: {state.get(\"review\")}')
print(f'grounding.valid: {state.get(\"grounding\", {}).get(\"valid\")}')
"
```

```bash
# Named validators resolve correctly with adapter wrappers
python -c "
from teleclaude.core.next_machine.validators import VALIDATOR_REGISTRY
for name, fn in VALIDATOR_REGISTRY.items():
    print(f'{name}: {fn.__module__}.{fn.__name__}')
"
```

```bash
# Language baseline loading
python -c "
from teleclaude.core.next_machine.engine import load_language_baseline
py = load_language_baseline('python')
ts = load_language_baseline('typescript')
missing = load_language_baseline('unknown')
print(f'python baseline: {len(py)} reads')
print(f'typescript baseline: {len(ts)} reads')
print(f'unknown language: {len(missing)} reads (graceful degradation)')
"
```

## Guided Presentation

### Step 1: The problem — hand-coded state machines

Open `teleclaude/core/next_machine/core.py`. Observe:
- 10 individual `_prepare_step_*` handler functions (lines 3004-3425), each
  hard-coding dispatch instructions
- `_prepare_dispatch()` (line 3433) routing by PreparePhase enum
- `next_work()` (line 3599) with a 300+ line if/elif chain routing by
  build/review status

Every new workflow step requires modifying Python code. The prepare and work
machines duplicate the same produce-review-iterate-approve pattern.

### Step 2: The solution — YAML workflow definitions

Open `workflows/prepare.yaml` and `workflows/work.yaml`. Each step is declared
with its producer command, reviewer command, required reads, artifacts, thinking
mode, state key, events, validators, thresholds, alt_commands, and pre_dispatch.
The same information that was embedded in Python handlers is now configuration.
Compare any step's YAML to its former handler to verify equivalence.

Highlight the expanded schema: the build step has `alt_commands: {bug:
next-bugs-fix}` and `pre_dispatch: "telec todo mark-phase {slug} ..."`. The
gates step has `validators: [build_gates, artifact_verification]`. The gate step
has `threshold: {dor_score: 8}`.

### Step 3: The engine interprets definitions

Open `teleclaude/core/next_machine/engine.py`. The engine loads a workflow
definition, reads state.yaml to determine the current step, and emits the exact
same dispatch instructions the old handlers produced. One engine, any workflow.
The step resolution functions (`resolve_prepare_step`, `resolve_work_step`)
replace the hand-coded routing with data-driven dispatch.

### Step 4: Named validators decouple verification from routing

Open `teleclaude/core/next_machine/validators.py`. Steps declare validators by
name in YAML. The registry maps names to adapter wrappers that delegate to
existing functions (`run_build_gates`, `verify_artifacts`). The adapter wrappers
normalize the different function signatures behind a uniform
`ValidatorFn(worktree_cwd, slug, phase, is_bug) -> (bool, str)` protocol. No
validation logic was duplicated or rewritten.

### Step 5: Language-aware code steps

Open `languages/python/baseline.md`. Code-producing steps (those with
`produces_code: true` in the YAML) automatically load this baseline when the
project's `teleclaude.yml` has `language: python`. The engine merges language
baseline context into the dispatch instruction's required_reads, giving workers
the right testing conventions without hard-coding language details in Python.

### Step 6: Behavioral equivalence proof

Run the characterization tests. Each test constructs a representative state,
calls the engine through `next_prepare()` or `next_work()`, and verifies the
dispatch output matches what the old hand-coded handlers would have produced.
Every reachable state combination is covered. The tests assert on
execution-significant fields (command, args, subfolder, next_call, pre_dispatch),
not on human-facing prose.

### Step 7: State compatibility

Existing `state.yaml` files continue to work without migration. The engine reads
the same `prepare_phase`, `build`, `review`, `grounding`, and review verdict
fields. Legacy todos without `prepare_phase` fall back to `_derive_prepare_phase()`
artifact-based derivation, same as before.
