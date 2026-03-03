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
4. **Test behavioral contracts, not documentation prose**
5. **Literal documentation string assertions are forbidden unless they are execution-significant**
6. **Write failing tests before production code — no exceptions**

### Test-Driven Development

Tests are requirements. Code is implementation of tests. Every behavioral change starts with a test that captures the expected behavior, fails because that behavior is missing, and then — and only then — gets the production code to make it pass.

**Iron law:** No production code without a failing test first. Code written before its test must be deleted and rewritten test-first. No keeping it "as reference." No "adapting" it. Delete means delete.

**RED-GREEN-REFACTOR cycle:**

1. **RED** — Write one focused test asserting the desired behavior. Run it. Confirm it fails for the right reason (missing behavior, not setup error).
2. **GREEN** — Write the smallest production change that makes the test pass. Nothing more.
3. **REFACTOR** — Clean up while all tests stay green. No new behavior in this step.

Verification checkpoints:

- RED: Test fails, failure message describes the missing behavior.
- GREEN: Test passes, no other tests broken, output clean.
- REFACTOR: All tests still green after cleanup.

**Rationalizations to reject:**

| Excuse                           | Reality                                                                           |
| -------------------------------- | --------------------------------------------------------------------------------- |
| "Too simple to test"             | Small code breaks. Test takes 30 seconds.                                         |
| "I'll test after"                | Tests passing immediately prove nothing — you never saw them catch the bug.       |
| "Tests after achieve same goals" | Tests-after answer "what does this do?" Tests-first answer "what should this do?" |
| "Already manually tested"        | Ad-hoc and non-repeatable. No record, can't re-run.                               |
| "Already wrote a lot of code"    | Sunk cost. Keeping unverified code is technical debt. Delete and restart.         |
| "Keep as reference"              | You'll adapt it. That's testing after. Delete means delete.                       |
| "Need to explore first"          | Fine. Throw away exploration, start with tests.                                   |
| "Hard to test"                   | Hard to test = hard to use. Simplify the design.                                  |
| "TDD slows me down"              | TDD is faster than debugging. Test-first is pragmatic.                            |
| "I can fix while I'm here"       | Mixed concerns hide behavior changes. Keep scope to the test.                     |
| "Existing code has no tests"     | You're improving it. Add tests for the code you touch.                            |

**Red flags — stop and restart with a test:**

- Production code exists without a corresponding failing test observed first.
- Test passes immediately on first run (testing existing behavior, not new behavior).
- Cannot explain why the test failed.
- Rationalizing "just this once."
- "It's about spirit not ritual" — violating the letter is violating the spirit.

### Documentation Assertion Guardrail

- Allowed: exact-string assertions for execution-significant text (for example parser markers, schema keys, command tokens, required reference prefixes) when runtime behavior depends on exact text.
- Forbidden: exact-string assertions for narrative wording, copy style, or editorial phrasing in docs/agent artifacts.
- Preferred: assert parsed structure, extracted references, idempotence, emitted behavior, or contract outcomes.

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
14. **Prose-lock tests** - tests that fail only because human-facing wording changed while behavior stayed the same

15. All tests run on every commit
16. Tests must pass before merging to main branch
17. Linting, type checking, and unit tests run automatically
18. No commits with `--no-verify` to bypass hooks unless explicitly approved
19. Keep test suite fast (< 10s for unit tests)

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
