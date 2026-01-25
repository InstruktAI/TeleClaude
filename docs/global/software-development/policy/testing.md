---
description:
  Pre-commit quality gates, test principles, linting, isolation, anti-patterns.
  Hooks-first verification.
id: software-development/policy/testing
scope: domain
type: policy
---

# Testing — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/code-quality
- @~/.teleclaude/docs/software-development/policy/linting-requirements

## Rule

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

@~/.teleclaude/docs/software-development/standards/linting-requirements.md

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
