# Requirements: TDD Enforcement with Single Test Contract

## Intent

Make TDD the default execution model across Next Machine so requirements are validated by approved tests authored up front, and builders/fixers cannot modify those tests during implementation.

## Why

Current flow allows implementation workers to change tests while coding, which weakens regression guarantees and breaks trust in test outcomes.

## Scope

### In scope

1. One canonical test-contract artifact per todo.
2. Preparation/gate flow that requires contract authoring and approval before build.
3. Runtime enforcement that blocks builder/fixer test-file edits.
4. Review/finalize checks that verify contract integrity.
5. CI/pre-commit guardrails for role-scoped test immutability.

### Out of scope

1. Rewriting all existing tests in the repository.
2. Migrating all historic todos retroactively in one step.
3. Replacing pytest/lint stack.
4. Changing feature behavior unrelated to TDD enforcement.

## Actor Model

1. Architect/Draft worker

- Writes and refines the test contract before build.

2. Gate worker

- Approves/rejects contract readiness.

3. Builder/Fixer

- Implements code only; cannot change locked tests.

4. Reviewer

- Verifies contract compliance and regression safety.

5. Finalizer/CI

- Enforces final policy gates before completion.

## Functional Requirements

### FR1: Canonical Test Contract Artifact

1. Each todo MUST include a deterministic test-contract file (for example `todos/{slug}/test-contract.md`).
2. The contract MUST define:

- required test files/cases,
- expected behavioral assertions,
- allowed exact-string assertions only when execution-significant,
- explicit non-goals.

3. Contract MUST include integrity metadata (hash/version + approval marker).

### FR2: Prep/Gate Ownership

1. `next-prepare-draft` owns contract drafting.
2. `next-prepare-gate` is the only phase allowed to mark contract approved/locked.
3. `next_work` MUST refuse build dispatch when contract is missing or not approved.

### FR3: Single Enforcement Mechanism

1. Enforcement MUST be uniform for build/fix paths (no special-case bypass).
2. Role-based behavior MUST come from one shared guard policy, not duplicated logic per command.

### FR4: Builder/Fixer Test Immutability

1. Builder and fixer commands MUST fail if they modify locked test files.
2. Failure response MUST be explicit and actionable (which file, which role, why blocked).
3. Worker must fix code to satisfy tests, not rewrite tests in build/fix lanes.

### FR5: Reviewer and Finalizer Contract Checks

1. Reviewer MUST verify contract still matches requirements and implementation behavior.
2. Finalizer/closing checks MUST verify contract hash did not change after lock (unless explicit re-gate flow happened).
3. Any contract change after lock MUST force re-entry to prepare gate.

### FR6: Policy/Docs Alignment

1. Build/fix procedures MUST explicitly prohibit test edits in those lanes.
2. Review procedure MUST include contract-integrity checks.
3. Templates MUST scaffold contract-first flow by default.

### FR7: Backward-Compatible Rollout

1. Existing todos without contract can continue only under explicit transitional mode.
2. New todos default to strict mode.
3. Transitional mode must be measurable and removable.

## Non-Functional Requirements

1. Deterministic outcomes: same repo state and role produce same pass/fail decision.
2. Low cognitive overhead: worker feedback must be short and precise.
3. Auditable: every block decision leaves clear evidence in logs/artifacts.

## Verification Requirements

1. `next_work` blocks when test contract missing/unapproved.
2. Builder attempt to change any locked test file is rejected.
3. Fixer attempt to change any locked test file is rejected.
4. Approved contract hash mismatch triggers re-gate requirement.
5. Reviewer/finalize checks fail when contract integrity is violated.
6. Transitional mode behavior is explicit and logged.

## Constraints

1. Reuse existing Next Machine architecture and phase model.
2. Keep enforcement in repo-local artifacts and standard git diff checks.
3. Do not introduce hidden fallback behavior.
