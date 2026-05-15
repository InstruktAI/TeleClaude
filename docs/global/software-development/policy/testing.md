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
- @~/.teleclaude/docs/software-development/policy/python/tooling.md

## Rules

1. **Use pre-commit hooks as the primary verification path**
2. **Do not run full suites by default** - Run targeted tests only when developing, debugging, or when hooks fail
3. Never commit code with failing hooks, lint violations, or type errors
4. **Test behavioral contracts, not human-facing text**
5. **String content assertions go through snapshots, named constants, or a narrow non-empty guard.** Literal, substring, prefix, suffix, and pattern comparisons against string content are forbidden in tests — no carve-outs. See "String Assertions — One Paradigm".
6. **Write failing tests before production code — no exceptions** (for new/modified code; see Characterization Testing for existing untested code)
7. **Tests-only scope is binding** — when the request or checkpoint scopes the work to tests only, production files are out of scope unless the human explicitly expands scope. If failing tests reflect a changed production contract, update the tests to the current public contract or stop and ask to broaden scope. Do not rewrite production code under a tests-only request.
8. In uv-managed Python repositories, run pytest through the uv-managed tool entrypoint: `uv run pytest ...`.

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
- String content is snapshot-covered or asserted via named constants — never by literal, substring, or pattern. See "String Assertions — One Paradigm".
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

### String Assertions — One Paradigm

Strings are never asserted by literal comparison, substring, `startswith`/`endswith`,
regex, or any pattern match against inline copy. No carve-outs.

Tests have **three permitted moves** on strings:

1. **Snapshot** — for any string the system emits. The snapshot is the contract.
2. **Non-empty guard** (`assert s` / `expect(s).toBeTruthy()`) — narrowly scoped to
   boundaries where accidental erasure is the failure mode. Asserts that *something*
   was produced, never *what*.
3. **Named-constant identity comparison** — when behavior depends on identity
   (e.g. `assert header == Headers.SESSION_ID`). Production and tests both import
   the constant; the constant's value is governed by a schema-level snapshot.

This applies uniformly to human-facing copy, contract-shaped strings (protocol
markers, schema keys, command tokens), and artifact/documentation strings. If
you find yourself writing `assert s == "some-literal"` against a protocol
identifier, the fix is a named constant — not a carve-out.

**Behavior stays structural.** Snapshots cover *presentation*. Errors are asserted
by exception type, states by enum/typed fields, diagnostics by their structured
fields. The rendered prose is snapshot-covered at the renderer's boundary.

**Exemption ledger.** A project-level file lists legacy test files that still
contain forbidden string assertions. Adding a new file is forbidden. Touching a
listed file means migrating its assertions in the same change and removing the
file from the ledger. The list drains over time.

**CI never updates snapshots.** Unreviewed snapshot deltas cannot land.

For framework-specific idioms, redaction patterns, inline-vs-file heuristics,
review workflow, and migration mechanics: see
`software-development/procedure/snapshot-testing`.

### Literal Echo and Primitive Side-Effect Guardrail

Tests must not merely mirror visible source literals or primitive library effects back to the reader.

- **Forbidden:** literal-echo assertions — rebuilding an expected dict/list/string from values already obvious in the implementation or fixture and asserting equality without proving any decision, transformation, validation, or failure handling.
- **Forbidden:** primitive side-effect assertions — proving only that a file/path/object/record exists after a direct library call when no application-owned branch, guard, validation, or error path was exercised.
- **Forbidden:** pass-through assertions that only prove data, props, config, or arguments were forwarded unchanged unless that forwarding behavior is itself the explicit public contract at the boundary under test.
- **Required question:** if the implementation were replaced with a constant, a trivial passthrough, or a single library call, would this test still pass? If yes, the test is weak and does not count as meaningful coverage.

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

### Browser Smoke Verification

Browser-rendered user-facing behavior must be verified in a real browser.

- When a delivery changes browser-based frontend or web UI behavior, run a Playwright smoke test that exercises the changed path.
- This is required in addition to unit and functional coverage.
- The builder records the exercised path and observed result in `quality-checklist.md`.
- The reviewer follows the same browser smoke verification path during review when feasible, and missing browser-smoke verification is a finding.

### Targeted Tests Only (Default)

Run the smallest test scope that proves the change. Escalate only when needed.

- Start with the specific failing test or closest affected test file
- Run a broader subset only if targeted tests are inconclusive
- Avoid running the entire suite unless explicitly required (release, CI parity, or missing hooks)

- Test behavior, not implementation
- **Each test pins exactly one behavioral path.** A "case" means a code-coverage path, not an input row. Multiple inputs that flow through the same path are redundant — one representative input is enough, one test, one assertion. Only when inputs exercise meaningfully different paths do they warrant separate tests, each with a name that documents the path it pins. `@pytest.mark.parametrize`, fixture `params=`, and equivalent table-driven patterns are forbidden — they invariably package either redundant runs through one path (waste) or distinct paths smuggled under one test body (forfeits per-path names and invites branches when bodies diverge). The cleanup of an existing parametrize block is **not** "split into N tests, one per row" — it is "identify the distinct paths, keep one test per path with one representative input, delete the rest."
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
14. **Prose-lock tests** — asserting on rendered text by literal, substring, prefix, suffix, or regex against inline copy. Snapshots are the only sanctioned path for any rendered text, human-facing or contract-shaped. See "String Assertions — One Paradigm"
15. **Testing third-party code** — never test that a library works. YAML round-trips, JSON serialization, `hashlib` output, ORM queries returning rows — these are the library's responsibility
16. **Testing informational side-effects** — audit timestamps, event emissions, log entries, metrics. If the system behaves identically when the side-effect is absent, the test has no value. Test the observability system, not every callsite that emits into it
17. **Tautological assertions** — asserting that a data literal contains keys visible in the source. The code that consumes the structure catches missing keys — that is the real test
18. **Truthy-check assertions used as content proxies** — `assert value` standing in for "the right thing was produced" is forbidden. The sanctioned use of `assert s` is the narrow non-empty boundary guard against accidental erasure (one canonical helper, one purpose). Anywhere else, snapshot the output or assert on the structured field that drives it
19. **Redundant coverage across files** — a function has one test home. Do not test the same function from multiple test files. Redundant tests multiply maintenance without adding safety
20. **Literal-echo tests** — reconstructing an expected literal from source-visible values and asserting equality without proving semantics, branching, validation, or failure handling
21. **Primitive side-effect tests** — only proving that a file/path/object/record was created or copied after a direct library call, without exercising application-owned logic
22. **Passthrough-only tests** — proving data flowed through unchanged when the forwarding itself is not the real behavior or decision under test
23. **Parametrized / table-driven tests** — multiple input rows stuffed into one test body via `@pytest.mark.parametrize`, fixture `params=`, or any equivalent mechanism. The deeper sin parametrize commits is **redundant coverage masquerading as more tests**: most parametrize tables are N inputs that all flow through the same code-coverage path. The unit of testing is the path, not the input. One representative input pins the path; additional inputs through the same path are waste. When inputs do exercise different paths, give each path its own named test that documents which path it pins. There is no legitimate use of parametrize — by construction it either packages redundant runs (delete the duplicates) or smuggles distinct paths under one body (split into named tests)
24. **String fragment / substring / pattern assertions** — `assert "x" in s`, `s.startswith(...)`, `s.endswith(...)`, regex matches against string content, partial-string `expect(s).toContain(...)`. Snapshot the full output, or assert on the structured field that drives the relevant fragment. Asserting on a fragment is the same prose-lock as asserting on the whole — it just hides the brittleness behind a smaller surface area
25. **Error-message text assertions** — asserting on exception `.message`, `.args[0]`, or rendered error prose. Test the exception *type* (`pytest.raises(SessionNotFoundError)`, `expect(...).toThrow(SessionNotFoundError)`) and the structured fields on it. The rendered prose is snapshot-covered separately, at the renderer's boundary

23. All tests run on every commit
24. Tests must pass before merging to main branch
25. Linting, type checking, and unit tests run automatically
26. No commits with `--no-verify` to bypass hooks unless explicitly approved
27. Keep test suite fast (< 10s for unit tests)

### Test Specification Delivery

Test specifications precede implementation plans. Specs are marked as expected failures using the
project's test framework mechanism. The suite stays green with specs present. When implementation
satisfies a spec, the expected-failure marker is removed. The marker mechanism is framework-specific —
the agent discovers it from the codebase.

### Escape-Hatch Docstring Ban

Specs whose docstrings defer behavioral coverage to non-automated verification are defective.
Phrases asserting that equivalence, correctness, or requirement satisfaction is "covered in a
checklist," "verified at integration level," "confirmed during build," or any variant that
routes a behavioral contract to a non-automated artifact, are rejected in spec review.

If the behavior cannot be unit-tested, the spec delivery must include a named integration spec
with an automated runner documented alongside the unit specs. A `quality-checklist.md` entry is
a human-facing summary, never a substitute for an automated assertion. The spec is the automated
contract; offloading the contract to prose is the same as not having a contract.

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

**Snapshot library per language:**

- **Python (pytest):** `syrupy`. Inline assertions via `assert value == snapshot`. Update with `uv run pytest --snapshot-update`. Redaction via `Matcher` / property paths.
- **TypeScript (vitest):** built-in `toMatchInlineSnapshot()` and `toMatchSnapshot()`. Update with `vitest -u` or watch-mode `u`. Redaction via asymmetric matchers (`expect.any(String)`, `expect.stringMatching(...)`).

The choice is canonical per runner — do not introduce alternative snapshot libraries.

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
