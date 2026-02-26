# Demo: api-todos-work-stability-hardening

## Validation

```bash
# Structural demo check (must pass in build gates)
telec todo demo validate api-todos-work-stability-hardening --project-root .
```

```bash
# Targeted next-machine tests for prep/sync/single-flight behavior
pytest -q tests/unit/test_next_machine_worktree_prep.py tests/unit/test_next_machine_hitl.py
```

```bash
# Run the same slug twice and inspect phase decision logs
telec todo work api-todos-work-stability-hardening || true
telec todo work api-todos-work-stability-hardening || true
instrukt-ai-logs teleclaude --since 30m --grep "NEXT_WORK_PHASE"
```

## Guided Presentation

### Medium

CLI + daemon logs.

### Step 1: Prove correctness gates still pass

Run the targeted unit tests. Observe they pass with the new conditional prep/sync
policy, proving no regression in next-machine behavior.

### Step 2: Demonstrate no redundant prep on unchanged repeated call

Run `telec todo work api-todos-work-stability-hardening` twice back-to-back.
Observe in logs that the second call emits prep decision metadata showing skip
for unchanged state, rather than re-running expensive prep each time.

### Step 3: Show phase-level timing visibility

Use `instrukt-ai-logs teleclaude --since 30m --grep "NEXT_WORK_PHASE"` and
observe phase-tagged timing entries (slug + phase + duration + decision reason).
This gives direct evidence for where `/todos/work` time is spent and whether
optimization decisions are working.
