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
4. **Test behavioral contracts, not human-facing text**
5. **Literal string assertions on any human-facing output are forbidden unless the exact text is execution-significant**
6. **Write failing tests before production code — no exceptions** (for new/modified code; see Characterization Testing for existing untested code)

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

| Excuse                           | Reality                                                                                                |
| -------------------------------- | ------------------------------------------------------------------------------------------------------ |
| "Too simple to test"             | Small code breaks. Test takes 30 seconds.                                                              |
| "I'll test after"                | Tests passing immediately prove nothing — you never saw them catch the bug.                            |
| "Tests after achieve same goals" | Tests-after answer "what does this do?" Tests-first answer "what should this do?"                      |
| "Already manually tested"        | Ad-hoc and non-repeatable. No record, can't re-run.                                                    |
| "Already wrote a lot of code"    | Sunk cost. Keeping unverified code is technical debt. Delete and restart.                              |
| "Keep as reference"              | You'll adapt it. That's testing after. Delete means delete.                                            |
| "Need to explore first"          | Fine. Throw away exploration, start with tests.                                                        |
| "Hard to test"                   | Hard to test = hard to use. Simplify the design.                                                       |
| "TDD slows me down"              | TDD is faster than debugging. Test-first is pragmatic.                                                 |
| "I can fix while I'm here"       | Mixed concerns hide behavior changes. Keep scope to the test.                                          |
| "Existing code has no tests"     | If changing it: characterize first, then TDD the change. If covering it: use characterization testing. |

**Red flags — stop and restart with a test:**

- Production code exists without a corresponding failing test observed first.
- Test passes immediately on first run (testing existing behavior, not new behavior).
- Cannot explain why the test failed.
- Rationalizing "just this once."
- "It's about spirit not ritual" — violating the letter is violating the spirit.

### Characterization Testing — Legacy Coverage

TDD drives design of new behavior. It cannot be applied to code that already exists and works — the
test would pass immediately, which TDD itself flags as a red flag. **Characterization testing** is
the sanctioned approach for systematically covering existing untested code.

A characterization test pins what the code _actually does_ at a meaningful boundary. It is a safety
net, not a specification. Its job is to detect unintended changes when the code is later modified.

**When characterization testing applies:**

- Systematic coverage campaigns for existing untested code.
- Covering a module before modifying it (characterize first, then TDD the change).
- Establishing regression guards for critical paths that lack tests.

**When characterization testing does NOT apply:**

- New features — use TDD.
- Bug fixes — use reproduction test delivery (RED first).
- Modifying existing behavior — characterize the current state, then TDD the change.

**OBSERVE-ASSERT-VERIFY cycle:**

1. **OBSERVE** — Run the code with representative inputs. Record actual outputs, side effects,
   return values, exceptions, and state changes.
2. **ASSERT** — Write a test that asserts the observed behavior at a public boundary. The test
   passes immediately — this is expected and correct for characterization.
3. **VERIFY** — Mutate the production code (introduce a deliberate fault). Confirm the test
   catches the mutation. If it doesn't, the test is too shallow — strengthen or discard it.

The mutation check in step 3 is what distinguishes a useful characterization test from a tautology.
A test that survives production mutations pins nothing.

**Characterization tests follow all other policy rules:**

- Behavioral contracts, not implementation details.
- No string assertions on human-facing text.
- Maximum 5 mock patches per test.
- Descriptive names that serve as behavioral specifications.
- One clear expectation per test.
- Mock at architectural boundaries only.
- Must answer: "What real bug in OUR code would this catch?"

**Boundary selection:** Characterize at public API boundaries — the functions and methods that
other modules actually call. Do not characterize private helpers, internal state, or implementation
details. If the boundary is hard to test, that signals design debt — document it, don't work
around it with deep mocking.

**Evolution:** When a module gets modified through TDD, its characterization tests either evolve
into specification tests or get pruned when the pinned behavior is intentionally changed. The safety
net gradually becomes the spec. This is organic — do not force the transition.

**Relationship to TDD iron law:** The iron law ("no production code without a failing test first")
governs all new and modified production code. Characterization testing governs coverage of existing
stable code. These are complementary, not competing — an agent doing coverage work follows
OBSERVE-ASSERT-VERIFY; an agent building new features follows RED-GREEN-REFACTOR. The distinction
is temporal: if the code exists, characterize; if it doesn't, TDD.

### Output Text Assertion Guardrail

Assert on data, structure, and behavior — never on how text reads. If the exact string could be reworded without changing what the system does, it is not a valid assertion target. Test the function that _produces_ the output, not the rendered text itself.

- **Allowed:** exact-string assertions for execution-significant text (parser markers, schema keys, command tokens, protocol identifiers, required reference prefixes) where runtime behavior depends on exact text.
- **Forbidden:** exact-string assertions on any human-facing output — composed messages, CLI help text, formatted reports, notification content, error prose, checkpoint messages, status output, agent artifacts, documentation. If the wording can change without changing behavior, the assertion is a prose-lock.
- **Preferred:** assert on the data structure the composer receives (action lists, category sets, flag values), return types, error codes/classes, presence of required fields — not on the string that gets rendered from them.

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
- Use shared setup helpers; keep them small and composable

1. Each test runs independently - no shared state between tests
2. Tests can run in any order
3. Use fresh instances/data for each test
4. Use mocks for all deps/boundaries to focus on code under test
5. Reset mocks between tests
6. Clean up global state in teardown

Every test must survive one question: **"What real bug in OUR code would this catch?"**

7. **Flaky tests** — non-deterministic tests that pass/fail randomly
8. **Slow tests** — tests that take seconds to run (indicates integration, not unit)
9. **Testing implementation details** — tests that break when refactoring without behavior change
10. **Over-mocking** — mocking everything makes tests brittle and proves nothing
11. **Mega tests** — one test that validates many behaviors; split into focused assertions
12. **No assertions** — tests that execute code but don't verify outcomes
13. **Commented-out tests** — either fix or delete them
14. **Prose-lock tests** — asserting on rendered text (messages, help output, reports, notifications) instead of on the data that produced it. These break when wording changes while behavior stays the same. Always assert on the underlying structure, never the composed string
15. **Testing third-party code** — never test that a library works. YAML round-trips, JSON serialization, `hashlib` output, ORM queries returning rows — these are the library's responsibility
16. **Testing informational side-effects** — audit timestamps, event emissions, log entries, metrics. If the system behaves identically when the side-effect is absent, the test has no value. Test the observability system, not every callsite that emits into it
17. **Tautological assertions** — asserting that a data literal contains keys visible in the source. The code that consumes the structure catches missing keys — that is the real test
18. **Truthy-check assertions** — `assert value` passes for any non-empty value. If a trivially wrong implementation satisfies the assertion, the assertion is worthless. Assert on specific expected values
19. **Redundant coverage across files** — a function has one test home. Do not test the same function from multiple test files. Redundant tests multiply maintenance without adding safety

20. All tests run on every commit
21. Tests must pass before merging to main branch
22. Linting, type checking, and unit tests run automatically
23. No commits with `--no-verify` to bypass hooks unless explicitly approved
24. Keep test suite fast (< 10s for unit tests)

### Test Specification Delivery

Test specifications precede implementation plans. Specs are marked as expected failures using the
project's test framework mechanism. The suite stays green with specs present. When implementation
satisfies a spec, the expected-failure marker is removed. The marker mechanism is framework-specific —
the agent discovers it from the codebase.

### Reproduction Test Delivery

Every bug fix starts with a test that reproduces the bug (RED). The reproduction test becomes a
permanent regression guard. "I verified manually" is not acceptable — if you can reproduce it,
you can test it.

### Test Spec Immutability

The builder cannot delete or weaken spec tests. The builder can remove expected-failure markers
(making tests active), can add new tests, and can refactor test structure while preserving all
assertions.

### Language and Framework Context

This policy is framework-agnostic. Test framework, runner commands, expected-failure markers, and
file patterns are project concerns — discover them from the codebase (package config, Makefile,
existing tests).

You MUST use `telec docs index | grep '{language}'` to surface language-specific doc snippets,
and use `telec docs get {snippet_id}` to read them ALL — they contain mandatory language idioms
for any code-producing work.

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
