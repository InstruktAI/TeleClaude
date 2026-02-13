# Implementation Plan: Test Suite Ownership Reset

## Overview

Restructure unit tests into explicit file ownership, keep functional tests active, and enforce path-based test gating so behavior changes cannot ship without relevant verification.

## Phase 1: Freeze + Contract

### Task 1.1: Activate rewrite freeze mode

- [ ] Announce temporary freeze policy for non-emergency feature work on main.
- [ ] Define emergency-fix exception flow with mandatory mapping/gate checks.

### Task 1.2: Define canonical ownership artifact

- [ ] Create `quality/path_test_map.yaml` schema and initial structure.
- [ ] Document mapping rules and naming convention.

## Phase 2: Inventory + Baseline Mapping

### Task 2.1: Inventory production files and current tests

- [ ] Generate list of `teleclaude/**/*.py` files in scope.
- [ ] Generate current unit test ownership candidates under `tests/unit/`.

### Task 2.2: Seed mapping baseline

- [ ] Populate first-pass one-to-one mappings.
- [ ] Mark unmapped files explicitly as blockers.

## Phase 3: Unit Test Rewrite

### Task 3.1: Rewrite by ownership slice

- [ ] For each source file, create/fix owning unit test file.
- [ ] Remove/replace brittle non-behavioral assertions.
- [ ] Keep tests focused on contract behavior of the owning file.

### Task 3.2: Maintain functional safety net

- [ ] Keep integration/functional tests running during rewrite.
- [ ] Patch any functional coverage gaps discovered during rewrites.

## Phase 4: Enforcement

### Task 4.1: Add path-based test gate

- [ ] Implement guard script resolving changed paths -> required tests.
- [ ] Fail on unmapped changed production paths.
- [ ] Fail when required tests fail or are skipped.

### Task 4.2: Add explicit no-impact path

- [ ] Support `test-impact: none` override with validation rules.
- [ ] Log/audit override use for review visibility.

## Phase 5: Rollout and Unfreeze

### Task 5.1: Dry run

- [ ] Run guard in report-only mode for a short trial window.
- [ ] Fix mapping and false positives.

### Task 5.2: Enforce

- [ ] Switch guard to blocking mode in commit/checkpoint flow.
- [ ] Unfreeze feature work only after mapping + guard + baseline pass are stable.

## Validation

- [ ] `make lint`
- [ ] targeted unit tests for rewritten ownership slices
- [ ] targeted integration/functional tests for touched behavior flows

## Definition of Done

- [ ] One-to-one unit ownership mapping exists for all in-scope production Python files.
- [ ] Path-based gate is active and blocking on missing/failing required tests.
- [ ] Non-behavioral prose-lock unit assertions are removed from active suite.
- [ ] Functional/integration safety net remains green.
