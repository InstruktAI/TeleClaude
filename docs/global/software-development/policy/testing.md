---
description: 'Pre-commit quality gates, test principles, linting, isolation, anti-patterns. Hooks-first verification.'
id: 'software-development/policy/testing'
scope: 'domain'
type: 'policy'
---

# Testing — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/code-quality.md
- @~/.teleclaude/docs/software-development/policy/linting-requirements.md

## Rules

1. **Use pre-commit hooks as the primary verification path**
2. **Do not run full suites by default** - Run targeted tests only when developing, debugging, or when hooks fail
3. Never commit code with failing hooks, lint violations, or type errors

### Test Levels (Required Strategy)

Use a layered approach: **unit → functional → smoke**. Each layer proves a different slice of the system.

1. **Unit tests** — isolated behavior with minimal dependencies.
   - Single function/class behavior, pure logic, data transforms.
   - Mock external boundaries (I/O, DB, network, adapters).
2. **Functional tests (integration chain tests)** — one chain of interaction, not full end-to-end.
   - Validate a focused segment of the flow (one actor communicating with another).
   - Mock the rest of the system to keep scope tight and behavior deterministic.
   - Avoid testing the entire user journey here.
3. **Smoke tests** — minimal end-to-end touches that hit all major paths.
   - Tiny, fast, and intentionally shallow.
   - Proves wiring across the application without deep assertions.

### Running Tests

- `make test` — run the full test suite (unit + integration)
- `make test-unit` — run unit tests only
- `make test-e2e` — run integration tests only
- Smoke tests live in `tests/integration/test_e2e_smoke.py` and run under `make test-e2e`.

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
