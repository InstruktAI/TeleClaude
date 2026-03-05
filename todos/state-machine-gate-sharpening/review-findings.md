# Review Findings: state-machine-gate-sharpening

## Critical

### C-1: `_has_meaningful_diff` over-subtracts files touched by both merge and non-merge commits

**File:** `teleclaude/core/next_machine/core.py:957-968`

The merge-commit filtering uses set subtraction (`changed_files -= set(merge_diff.stdout.splitlines())`) which removes a file from the "meaningful" set if *any* merge commit touched it — even if a non-merge commit also modified the same file. This causes false negatives: the function returns `False` (no meaningful diff) when it should return `True`, allowing a stale review approval to proceed to finalize unchecked.

**Concrete scenario:** A merge from main introduces changes to `core.py`. A regular commit on the branch also changes `core.py`. The diff shows `core.py` changed. The merge commit subtraction removes `core.py`. Function returns `False`. Stale review approval persists.

This violates the function's own documented fail-safe contract: "Returns True on subprocess errors (fail-safe: assume meaningful diff, invalidate)." The same fail-safe intent should apply to ambiguous merge overlaps.

**Fix:** Compute files changed by non-merge commits explicitly, rather than subtracting merge files from the total diff. Check if non-merge commits touch any non-infrastructure files.

### C-2: `_has_meaningful_diff` called synchronously on async event loop

**File:** `teleclaude/core/next_machine/core.py:3008`

```python
head_sha = await asyncio.to_thread(_get_head_commit, worktree_cwd)
if baseline and head_sha and baseline != head_sha and _has_meaningful_diff(worktree_cwd, baseline, head_sha):
```

`_get_head_commit` (one subprocess call) is correctly wrapped in `asyncio.to_thread`. `_has_meaningful_diff` (N+2 subprocess calls: one diff, one rev-list, one per merge commit) is called **directly on the event loop thread**. Each `subprocess.run` call blocks the event loop. Under load, this causes timeouts or sluggish responses for concurrent work items.

**Fix:** Wrap in `asyncio.to_thread`:
```python
if baseline and head_sha and baseline != head_sha and await asyncio.to_thread(
    _has_meaningful_diff, worktree_cwd, baseline, head_sha
):
```

### C-3: Demo references wrong test file

**File:** `demos/state-machine-gate-sharpening/demo.md` block 4

The demo runs `pytest tests/unit/test_next_machine_state_deps.py -v -k "stale_baseline or gate_failure_review or test_failures"` but the actual tests live in `tests/unit/test_state_machine_gate_sharpening.py`. The referenced file contains no tests matching the `-k` filter — the command exercises zero new tests.

**Fix:** Replace `test_next_machine_state_deps.py` with `test_state_machine_gate_sharpening.py`.

## Important

### I-1: No logging on `_has_meaningful_diff` subprocess errors

**File:** `teleclaude/core/next_machine/core.py:973-974`

The outer exception handler returns `True` (fail-safe) with zero logging. An operator seeing `review_approval_stale_baseline` in logs will conclude a real diff was detected, when a subprocess error actually occurred. The cause of review invalidation is invisible.

**Fix:** Add `logger.warning` before returning `True`, including `cwd`, `baseline`, `head`, and the exception.

### I-2: Retry path hardcodes test config paths, diverging from original `make test` environment

**File:** `teleclaude/core/next_machine/core.py:439-443`

```python
retry_env = {
    **os.environ,
    "TELECLAUDE_CONFIG_PATH": "tests/integration/config.yml",
    "TELECLAUDE_ENV_PATH": "tests/integration/.env",
}
```

The initial `make test` call uses no explicit `env=` parameter (inheriting the current process environment). The retry constructs a custom env with hardcoded config paths. If the Makefile's `test` target sets different paths, the retry runs under different configuration. The retry could pass when the original would still fail (or vice versa), undermining the flaky-test retry purpose.

**Fix:** Either omit the custom env (let `pytest --lf` inherit the same environment), or extract the env-setup from the Makefile and share it. At minimum, add a comment explaining why these paths are needed.

### I-3: Demo block 3 grep produces no output

**File:** `demos/state-machine-gate-sharpening/demo.md` block 3

`grep -A5 "review_approval_stale_baseline" | grep "_has_meaningful_diff"` would produce no output. `_has_meaningful_diff` is at line 3008, which is 11 lines *before* the log string at line 3019, not within 5 lines after it.

**Fix:** Adjust the grep to use `-B15` or target the actual guard condition directly, e.g.:
```bash
grep -B5 "_has_meaningful_diff" teleclaude/core/next_machine/core.py | head -10
```

### I-4: Missing test — retry `TimeoutExpired`/`OSError` handler

**File:** `tests/unit/test_state_machine_gate_sharpening.py`

The production code at `core.py:464-469` has an explicit `except (subprocess.TimeoutExpired, OSError)` handler for when the retry subprocess fails. This error path is not tested. A refactor could silently drop the handler and cause an unhandled crash mid-gate-check.

**Fix:** Add a test where `make test` fails with 1 failure but the retry `subprocess.run` raises `subprocess.TimeoutExpired`. Assert `passed is False` and `"RETRY ERROR"` in output.

### I-5: Missing test — artifact verification failure with `review_round > 0`

**File:** `tests/unit/test_state_machine_gate_sharpening.py`

The artifact verification failure path (`core.py:3109-3119`) has the exact same `review_round` conditional as the build gate path, but only the build gate path is tested. A future edit could fix one path and forget the other.

**Fix:** Add tests mirroring `test_next_work_gate_failure_review_round_*` but with `run_build_gates` returning `(True, ...)` and `verify_artifacts` returning `(False, ...)`.

## Suggestions

### S-1: Variable shadowing — `merge_commit` loop variable reassigned

**File:** `teleclaude/core/next_machine/core.py:957-958`

`merge_commit` is the loop variable and is immediately reassigned via `.strip()`. Using distinct names (`raw_line` / `merge_sha`) improves readability.

### S-2: `_count_test_failures` regex — first vs. last match

**File:** `teleclaude/core/next_machine/core.py:408-411`

`re.search` returns the first match. In verbose pytest output, assertion messages could contain "N failed" before the summary line. Using `re.findall(...)[-1]` would be more robust. Low probability in practice.

### S-3: Missing logging on inner merge-commit catch

**File:** `teleclaude/core/next_machine/core.py:969-970`

The `continue` on `CalledProcessError` is best-effort and biases toward invalidation (correct direction), but a `logger.debug` would make degradation traceable.

### S-4: Comment parity for artifact "keep build complete" decision

**File:** `teleclaude/core/next_machine/core.py:3118`

The build gate path has a comment at line 3099 explaining the `review_round > 0` behavior. The artifact path at line 3118 lacks the same comment.

## Why No Issues — Paradigm Fit

1. **Patterns checked:** `asyncio.to_thread` wrapping, `read_phase_state` / `mark_phase` pipeline, private helper naming, type-coercion pattern, `subprocess.run` usage in `_get_head_commit`.
2. **Requirements validated:** All seven success criteria (SC-1 through SC-7) have corresponding code paths and test coverage. Conditional logic at gate failure matches requirements exactly.
3. **Copy-paste checked:** No duplication detected — the three features are distinct functions/branches. The `review_round` conditional appears in two places (build gate, artifact verification) intentionally for the same logic.

## Verdict: REQUEST CHANGES

3 Critical, 5 Important, 4 Suggestions. The merge-commit over-subtraction (C-1) violates the stated fail-safe contract, the synchronous event loop call (C-2) is a correctness bug in async code, and the demo references the wrong file (C-3).
