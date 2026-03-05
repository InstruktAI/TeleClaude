# Implementation Plan: state-machine-gate-sharpening

## Overview

Three surgical fixes in `teleclaude/core/next_machine/core.py`. Each fix addresses a distinct
false-invalidation pattern that burns orchestrator cycles. All changes are backward-compatible:
they narrow existing reset conditions, never widen them.

## Phase 1: Core Changes

### Task 1.1: Merge-aware stale baseline guard

**File(s):** `teleclaude/core/next_machine/core.py` (lines 3004–3022)

- [x] Add helper `_has_meaningful_diff(cwd: str, baseline: str, head: str) -> bool` that:
  1. Runs `git -C {cwd} diff --name-only {baseline}..{head}` to get changed file paths.
  2. Filters out paths starting with `todos/` or `.teleclaude/`.
  3. Filters out merge commits: runs `git -C {cwd} rev-list --merges {baseline}..{head}` and
     for each merge commit, gets its changed files via `git diff --name-only {merge}^..{merge}`;
     removes those files from the diff set (they were introduced by merge, not by new work).
  4. Returns `True` if any files remain after filtering, `False` otherwise.
  5. On subprocess error, returns `True` (fail-safe: assume meaningful diff, invalidate).
- [x] Replace the simple SHA comparison at line 3010 (`baseline != head_sha`) with a call
      to `_has_meaningful_diff(worktree_cwd, baseline, head_sha)`.
- [x] Keep the guard structure: only invalidate when `_has_meaningful_diff` returns `True`.

### Task 1.2: Preserve build on gate failure when review already occurred

**File(s):** `teleclaude/core/next_machine/core.py` (lines 3087–3097)

- [x] Read `review_round` from `state` (already loaded at line 2983) before the gate check.
- [x] After gate failure (line 3090), check `review_round > 0`:
  - If `review_round > 0`: do NOT reset build to `started`. Keep `build=complete`.
    The gate failure response still fires, but the builder gets a focused fix instruction
    instead of a full rebuild.
  - If `review_round == 0`: reset build to `started` (existing behavior).
- [x] Apply the same conditional to the artifact verification failure block (lines 3105–3111).
- [x] Update the log detail string to distinguish: `"build_gates_failed_post_review"` vs
      `"build_gates_failed"`.

### Task 1.3: Single retry for low-count test failures

**File(s):** `teleclaude/core/next_machine/core.py` (function `run_build_gates`, lines 416–471)

- [x] Add helper `_count_test_failures(output: str) -> int` that parses pytest summary line
      for failure count. Regex: `r"(\d+) failed"`. Returns 0 if no match found.
- [x] After test failure (line 433), call `_count_test_failures(test_result.stdout)`.
- [x] If failure count is between 1 and 2 (inclusive):
  1. Run retry: `pytest --lf -q` in the worktree with 120s timeout.
     Use the venv python: `{worktree_cwd}/.venv/bin/pytest` or fall back to `pytest` in PATH.
     Set env vars: `TELECLAUDE_CONFIG_PATH=tests/integration/config.yml`,
     `TELECLAUDE_ENV_PATH=tests/integration/.env` (same as `tools/test.sh`).
  2. If retry passes (returncode 0): set gate as passed, append
     `"GATE PASSED: make test (retry passed after {N} flaky failure(s))"`.
  3. If retry fails: gate fails, append combined output from both runs.
- [x] If failure count > 2 or unparseable: no retry, existing behavior.

---

## Phase 2: Validation

### Task 2.1: Tests

- [x] Test `_has_meaningful_diff`: mock `subprocess.run` to return various file lists,
      verify filtering of `todos/`, `.teleclaude/`, merge commits.
- [x] Test `_has_meaningful_diff` subprocess error: returns `True` (fail-safe).
- [x] Test stale baseline guard integration: review approved + only infrastructure diff = approval holds.
- [x] Test stale baseline guard integration: review approved + real diff = approval invalidated.
- [x] Test gate failure with `review_round > 0`: build stays `complete`.
- [x] Test gate failure with `review_round == 0`: build resets to `started`.
- [x] Test `_count_test_failures`: various pytest output strings.
- [x] Test `run_build_gates` retry path: mock test failure with 1-2 failures, verify retry runs.
- [x] Test `run_build_gates` no retry: mock test failure with >2 failures, verify no retry.
- [x] Run `make test`

### Task 2.2: Quality Checks

- [x] Run `make lint` — pre-existing failures in `docs/third-party/art-of-hosting/` (introduced in `17d5554f`, unrelated to this slug)
- [x] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable) — no deferrals
