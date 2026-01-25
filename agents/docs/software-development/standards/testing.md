---
description:
  Pre-commit quality gates, test principles, linting, isolation, anti-patterns.
  Hooks-first verification.
id: software-development/standards/testing
scope: domain
type: policy
---

# Testing Standards — Policy

## Required reads

- @software-development/standards/code-quality
- @software-development/standards/linting-requirements

## Requirements

@~/.teleclaude/docs/software-development/standards/code-quality.md

## Pre-Commit Quality Gates

1. **Use pre-commit hooks as the primary verification path**
2. **Do not run full suites by default** - Run targeted tests only when developing, debugging, or when hooks fail
3. Never commit code with failing hooks, lint violations, or type errors

### Targeted Tests Only (Default)

Run the smallest test scope that proves the change. Escalate only when needed.

- Start with the specific failing test or closest affected test file
- Run a broader subset only if targeted tests are inconclusive
- Avoid running the entire suite unless explicitly required (release, CI parity, or missing hooks)

## Test Quality Principles

- Test behavior, not implementation
- Prefer one clear expectation per test
- Keep tests deterministic and fast
- Cover edge cases and error paths before happy paths
- Test public interfaces, not private internals
- Mock at architectural boundaries; avoid over-mocking
- Use clear, descriptive test names
- Use fixtures for shared setup; keep them small and composable

## Linting & Type Checking

@~/.teleclaude/docs/software-development/standards/linting-requirements.md

## Test Isolation

1. Each test runs independently - no shared state between tests
2. Tests can run in any order
3. Use fresh instances/data for each test
4. Use mocks for all deps/boundaries to focus on code under test
5. Reset mocks between tests
6. Clean up global state in teardown

## Testing Anti-Patterns to Avoid

1. **Flaky tests** - non-deterministic tests that pass/fail randomly
2. **Slow tests** - tests that take seconds to run (indicates integration, not unit)
3. **Testing implementation details** - tests that break when refactoring
4. **Over-mocking** - mocking everything makes tests brittle
5. **Mega tests** - one test that validates many behaviors
6. **No assertions** - tests that execute code but don't verify outcomes
7. **Commented-out tests** - either fix or delete them

## Continuous Integration Standards

1. All tests run on every commit
2. Tests must pass before merging to main branch
3. Linting, type checking, and unit tests run automatically
4. No commits with `--no-verify` to bypass hooks unless explicitly approved
5. Keep test suite fast (< 10s for unit tests)

## Pre-Commit Checklist

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
