# Demo: state-machine-gate-sharpening

## Validation

```bash
# Verify the three new helpers exist in core.py
grep -n "def _has_meaningful_diff" teleclaude/core/next_machine/core.py
grep -n "def _count_test_failures" teleclaude/core/next_machine/core.py
```

```bash
# Verify stale baseline guard uses diff-based check instead of SHA comparison
grep -A5 "review_approval_stale_baseline" teleclaude/core/next_machine/core.py | grep "_has_meaningful_diff"
```

```bash
# Verify gate failure preserves build when review_round > 0
grep -B2 -A5 "build_gates_failed_post_review" teleclaude/core/next_machine/core.py
```

```bash
# Run the unit tests for the new behavior
pytest tests/unit/test_next_machine_state_deps.py -v -k "stale_baseline or gate_failure_review or test_failures" --no-header
```

```bash
# Full test suite passes
make test
```

## Guided Presentation

### Step 1: Merge-aware stale baseline guard

**Do:** Open `teleclaude/core/next_machine/core.py` and search for `_has_meaningful_diff`.

**Observe:** The function runs `git diff --name-only` between baseline and HEAD, filters out
`todos/` and `.teleclaude/` paths, excludes merge-introduced files, and returns whether
meaningful (non-infrastructure) changes exist.

**Why it matters:** Previously, any SHA mismatch after review approval triggered re-review —
even when the only changes were merge commits from main or orchestrator state updates. This
burned review rounds and blocked finalize. Now only real code changes invalidate approval.

### Step 2: Build preservation on gate failure after review

**Do:** Search for `build_gates_failed_post_review` in the same file.

**Observe:** When `review_round > 0` (meaning review already happened), gate failure no longer
resets build to `started`. The builder gets a focused fix instruction without re-dispatching
a full `/next-build`.

**Why it matters:** After review round 1+, the builder has already built everything. Resetting
to `started` forced a full rebuild cycle — wasted tokens and time. Now the orchestrator sends
the failure details and the builder fixes only what's broken.

### Step 3: Flaky test retry

**Do:** Search for `_count_test_failures` and the retry block in `run_build_gates`.

**Observe:** When pytest reports ≤2 failures, the gate runner retries with `pytest --lf`. If
the retry passes, the gate passes. The output logs the retry for auditability.

**Why it matters:** The async teardown pattern causes ~50% of gate runs to see 1-2 flaky
failures in a 2500+ test suite. Without retry, every flaky failure forces a full builder
round-trip. The single retry catches the common case while still failing on real regressions.
