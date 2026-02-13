# Requirements: Test Suite Ownership Reset

## Intent

Stabilize delivery by making test ownership explicit and enforceable without replacing the entire current test system.

## Why

Regressions keep returning because test expectations and implementation intent drift across sessions. The repo needs deterministic ownership and deterministic gating.

## Scope

### In scope

1. Define one-to-one ownership for unit tests:
   - `teleclaude/.../foo.py` -> `tests/unit/.../test_foo.py`.
2. Keep functional/integration tests as an active behavior safety net.
3. Remove or rewrite unit tests that only lock non-behavioral wording/style details.
4. Introduce a machine-readable path-to-test mapping used by commit/checkpoint gates.
5. Require changed code paths to run mapped tests (plus required functional tests).
6. Add an explicit escape valve for no-behavior-change refactors (`test-impact: none`).

### Out of scope

1. Replacing pytest/tooling stack.
2. Eliminating integration test mocking entirely.
3. Full architecture redesign unrelated to test ownership and enforcement.

## Functional Requirements

### FR1: Unit Test Ownership Contract

1. Every production Python file in `teleclaude/` must have a declared owning unit test file path.
2. Ownership mapping must be stored in one canonical artifact (for example `quality/path_test_map.yaml`).
3. Unmapped production files are not allowed once rollout is complete.

### FR2: Behavior-First Test Quality

1. Unit tests must validate behavior/contracts of the owning source file.
2. Non-behavioral prose-lock assertions must be removed.
3. Exact string assertions are allowed only when execution-significant.

### FR3: Functional Safety Net

1. Integration/functional tests remain required and executable during and after rewrite.
2. Critical end-to-end behaviors must stay covered while unit tests are reorganized.

### FR4: Deterministic Enforcement

1. For any changed production path, gate logic must resolve required tests from the mapping.
2. Commit/checkpoint must fail if:
   - required tests fail,
   - a changed production file has no mapping,
   - required test run is skipped without explicit allowed reason.
3. `test-impact: none` must be explicit and auditable.

### FR5: Freeze Window Discipline

1. During the rewrite window, mainline feature work is frozen except emergency fixes.
2. Emergency fixes must still honor path-to-test mapping and gating.
3. Worktree side work is allowed but must reconcile through the same gating rules before merge.

## Non-Functional Requirements

1. Low cognitive overhead: agents can determine required tests from changed paths automatically.
2. High auditability: each gate decision explains which paths mapped to which tests.
3. Predictable runtime: targeted test runs first; broader runs only when needed.

## Verification Requirements

1. Mapping validation job fails on missing/invalid mappings.
2. Path-based gate correctly selects required tests for changed files.
3. Gate blocks commits when mapped tests are failing.
4. Gate blocks commits when unmapped production files are changed.
5. Escape valve usage is visible in logs/commit metadata.

## Constraints

1. Must align with current commit, testing, and DOR policies.
2. Must preserve active integration/functional test pipeline throughout transition.
3. Must be incremental and reversible if rollout issues appear.
