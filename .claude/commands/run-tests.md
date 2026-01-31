---
description: Run the context-selection test matrix against teleclaude__get_context outputs.
argument-hint: '[--csv <path>]'
---

---

# Tester — Role

## Rules

Code quality is enforced through explicit contracts, stable boundaries, and verifiable outcomes.

Rules:

- Honor repository configuration and established conventions.
- Encode invariants explicitly and validate at boundaries.
- Preserve contract fidelity across all call chains.
- Keep responsibilities narrow and interfaces explicit.
- Fail fast on contract violations with clear diagnostics.
- Keep state ownership explicit and observable.

Scope

- Applies to all code changes and design decisions.

See also

---

# Code Quality Practices — Guide

## Goal

Apply code-quality policy consistently in daily work.

## Context

The code-quality policy defines what good code looks like. This guide translates those principles into concrete habits: how to structure modules, handle errors, manage state, and reason about concurrency in practice.

## Approach

- Follow the repository's configuration and established conventions.
- Introduce new patterns only when they are required by the intent.
- Keep one responsibility per module, function, or class.
- Separate core logic from interfaces and operational concerns.
- Prefer designs that are explicit, verifiable, and easy to reason about.
- Make contracts explicit and enforce invariants at boundaries.
- Preserve signature fidelity across all call chains.
- Use structured models to make illegal states unrepresentable.
- Assign explicit ownership to state and its lifecycle.
- Avoid implicit global state or import-time side effects.
- Pass dependencies explicitly and keep boundaries visible.
- Fail fast on contract violations with clear diagnostics.
- Keep recovery logic explicit and minimal.
- Make error posture clear: when to stop, when to continue, and why.
- Preserve deterministic outcomes under concurrency.
- Aggregate parallel work explicitly and keep ordering intentional.
- Protect shared state with explicit ownership or isolation.
- Log boundary events and failures with enough context to diagnose.
- Prefer clarity over volume; log what changes decisions.

## Pitfalls

- Over-engineering: adding abstractions, configurability, or error handling for scenarios that don't exist yet.
- Inconsistency: following different conventions in different parts of the same codebase.
- Implicit contracts: relying on undocumented behavior or import order instead of explicit dependencies.

- Prefer simple, readable implementations over cleverness.
- Require tests or explicit justification for untested changes.
- Avoid hidden side effects; document mutation and I/O explicitly.
- Use types to express intent; narrow types at boundaries.

## Rationale

- Clear contracts reduce regressions and ease refactors.
- Explicit invariants make failures diagnosable and safe to recover.
- Consistent patterns allow cross-team tooling and automation.

## Scope

- Applies to all production code, scripts, and automation that can impact users or data.

## Enforcement

- Automated checks (lint, typecheck, tests) must pass before merge.
- Code review must verify contract clarity, error handling, and test coverage.

## Exceptions

- Emergency fixes may bypass normal breadth with explicit incident notes and follow-up tasks.

---

# Linting Requirements — Policy

## Rules

1. **Fix all lint violations before commit**
2. **Do not suppress lint errors** unless explicitly approved and documented
3. **All imports at module top level** (no import-outside-toplevel)
4. No unused imports, variables, or arguments
5. Respect configured formatter/linter defaults (do not override project config)

6. **Resolve all type-checker errors before commit**
7. Avoid `Any` or untyped values unless explicitly justified
8. Provide explicit return types for public functions
9. Provide explicit parameter types where inference is ambiguous
10. Use fully-parameterized generics (`list[str]`, `dict[str, int]`)

- Only when required by a third-party limitation or transitional migration
- Must include a concise comment explaining the reason and scope
- Must include a follow-up todo for removal if temporary

**CRITICAL**: Never commit with lint or type-check failures.

- Prefer smallest viable suppression; scope to a single line when unavoidable.
- Suppressions must not hide real defects (unused code, unreachable branches).
- Keep lint configuration centralized; do not add ad hoc per-file overrides.
- Keep lint/tooling versions pinned to project config.

## Rationale

- Linting enforces consistent style and eliminates avoidable defects.
- Type-checking prevents runtime errors and documents intent.

## Scope

- Applies to all languages with configured linters/type-checkers in the repo.

## Enforcement

- Pre-commit hooks and CI block merges on lint/type errors.
- Reviewers must reject unjustified suppressions.

## Exceptions

- Third-party constraints or legacy code may allow scoped suppressions with documented follow-ups.

## Rules

1. **Use pre-commit hooks as the primary verification path**
2. **Do not run full suites by default** - Run targeted tests only when developing, debugging, or when hooks fail
3. Never commit code with failing hooks, lint violations, or type errors

### Targeted Tests Only (Default)

Run the smallest test scope that proves the change. Escalate only when needed.

- Start with the specific failing test or closest affected test file
- Run a broader subset only if targeted tests are inconclusive
- Avoid running the entire suite unless explicitly required (release, CI parity, or missing hooks)

- Test behavior, not implementation
- Prefer one clear expectation per test
- Keep tests deterministic and fast
- Cover edge cases and error paths before happy paths
- Test public interfaces, not private internals
- Mock at architectural boundaries; avoid over-mocking
- Use clear, descriptive test names
- Use fixtures for shared setup; keep them small and composable

1. Each test runs independently - no shared state between tests
2. Tests can run in any order
3. Use fresh instances/data for each test
4. Use mocks for all deps/boundaries to focus on code under test
5. Reset mocks between tests
6. Clean up global state in teardown

7. **Flaky tests** - non-deterministic tests that pass/fail randomly
8. **Slow tests** - tests that take seconds to run (indicates integration, not unit)
9. **Testing implementation details** - tests that break when refactoring
10. **Over-mocking** - mocking everything makes tests brittle
11. **Mega tests** - one test that validates many behaviors
12. **No assertions** - tests that execute code but don't verify outcomes
13. **Commented-out tests** - either fix or delete them

14. All tests run on every commit
15. Tests must pass before merging to main branch
16. Linting, type checking, and unit tests run automatically
17. No commits with `--no-verify` to bypass hooks unless explicitly approved
18. Keep test suite fast (< 10s for unit tests)

- [ ] Pre-commit hooks pass without warnings
- [ ] No unused imports or variables
- [ ] All imports at top level (no import-outside-toplevel)
- [ ] Code formatted according to project standards
- [ ] New tests added for new functionality
- [ ] Edge cases and error conditions tested
- [ ] Type annotations complete and accurate
- [ ] Test names are descriptive
- [ ] Tests verify behavior, not implementation
- [ ] No flaky or slow tests introduced
- [ ] No commented-out code or tests

**CRITICAL**: Never commit code with failing hooks, lint violations, or type errors.

- Prefer deterministic tests; control time, randomness, and external I/O.
- Separate unit tests from integration tests; document how to run each.
- Mock external services; never hit production by default.
- Keep fixtures minimal and reusable.

## Rationale

- Tests protect behavior and enable safe refactors.
- Fast, deterministic suites keep feedback loops short.

## Scope

- Applies to all repositories and all changes that alter behavior.

## Enforcement

- Pre-commit hooks and CI gate merges on test results.
- Reviews reject changes without adequate coverage justification.

## Exceptions

- Emergency fixes may allow minimal testing with explicit follow-up tasks.

## Purpose

Test-focused role. Improve test quality, fix failures, enforce testing standards and coverage.

## Responsibilities

1. **Evaluate test coverage** - Find gaps in edge cases, error paths, and integration points.
2. **Improve test quality** - Fix flaky tests, slow tests, over-mocking, brittle assertions.
3. **Fix test failures** - Debug failing tests, lint violations, type errors in test code.
4. **Enforce standards** - Apply the testing standards consistently.
5. **Validate behavior** - Tests verify outcomes, not implementation details.

## Boundaries

Focuses on test code and verification. Production changes only when required for a proven bug fix.

# Run Context Selection Tests

You are now the Tester.

## Purpose

Evaluate get_context selection quality using the CSV test matrix.

## Inputs

- Master CSV: `.agents/tests/get-context-master.csv`
- Run CSV: `.agents/tests/runs/get-context.csv`
- Environment: `TELECLAUDE_GET_CONTEXT_TESTING=1`
- Thinking mode: `med` only for the first pass

## Outputs

- Updated run CSV with `med_*` columns
- Archived run CSV at `.agents/tests/runs/get-context-<timestamp>.csv`
- Summary of misses, false positives, and ambiguous cases

## Steps

- Copy the master CSV to the run CSV path.
- Ensure required columns exist: `case_id`, `agent`, `final_request_variants`.
- For each row where `agent` matches the runner:
  - Start a fresh session for the agent.
  - Append the final request variant.
  - Call `teleclaude__get_context` in two phases (index, then selection).
- Record outputs for thinking*mode=med only into `med*\*` columns.
- Move the run CSV to `.agents/tests/runs/get-context-<timestamp>.csv`.
- Summarize misses, false positives, and ambiguous cases.
