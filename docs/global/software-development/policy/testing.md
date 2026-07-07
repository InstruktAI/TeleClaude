---
description: 'Testing doctrine: tests bind human-authored feature-spec scenarios; functional + smoke as the levels; coverage measured against the scenario inventory; spec-mirrored test files; spec-driven RED-GREEN delivery; drift caught by the spec → test → code change process. Language specifics live in the per-language testing policy.'
visibility: 'public'
---

# Testing — Policy

## Rules

### What a test is

1. **Tests bind feature-spec scenarios; they never invent assertions.** Every test names the
   scenario it realizes — `<spec_id>` and a stable scenario id (`UC-<area><n>`). The human-authored
   Gherkin (`Given / When / Then`) is the contract; the test body only drives the real system to
   exercise that scenario. An agent binds an unbound scenario — it does not author the assertion.
   **A test that binds no scenario and is not a smoke/wiring check (rule 5) must not exist — do not
   write it, and delete it if it is already there. A missing bindable scenario is the reason there
   is no test, never a licence to invent one.**
2. **The scenario author and the test binder are distinct roles.** The Product Owner authors and
   freezes a scenario (human-driven, agent-assisted, at intake); a later build pass binds it. A test
   is never written by the same pass that authored its scenario — that is grading one's own work and
   collapses the guarantee. The bug lane, which has no intake, carries one bounded exception: the
   bug's plan phase authors at most one pending regression scenario encoding exactly the reported
   symptom (see `lifecycle/prepare/plan-draft`, bug-scope clamp), and the build pass binds it — the
   author/binder separation holds across the phases. Any scenario beyond that one is invention, not
   the exception.
3. **No agent-authored unit tests where no compiler enforces unit-level correctness.** In such
   languages (e.g. Python, TypeScript) behavior is verified by functional and smoke tests only. A
   compiled language whose type system enforces unit-level correctness keeps colocated unit tests as
   a documented exception — see the per-language testing policy.

### Levels

4. **Functional is the primary level.** One real interaction chain at a boundary: real in-process
   components, mocking only what crosses the process or network line. Each functional test asserts
   its own boundary contract — the shape, event, or response it emits or consumes — so composition
   is trustworthy without broad end-to-end tests. What counts as the boundary, which mocks are
   legitimate (only the process or network line), and the tells of a unit test wearing the
   functional label are defined in `software-development/concept/functional-test-boundary`. The
   marker is self-asserted by the author and proves nothing; the functional-versus-unit distinction
   is a review judgment against that definition, never a path check or a scanner.
5. **Smoke proves wiring, machine-checkably.** A small set of tests assert concrete wiring facts —
   services registered, routes mounted, the bus subscribed, one request flowing end to end. "It
   started without crashing" is not a smoke test; assert the structural facts.
6. **Integration is a rare, justified exception.** Reserved for behavior that cannot be faked at the
   functional level — real external-system semantics (a broker's redelivery rules, a database's
   isolation behavior). Not a tier to grow; a short list, each entry justified.

### File organization

7. **One test file per feature spec, path-mirrored.** A feature spec at
   `docs/project/spec/feature/<domain>/<slug>.md` is covered by a single test file at
   `tests/<domain>/test_<slug>.<ext>`. Domains are `snake_case`; spec slugs are `kebab-case`; the
   `<slug>` in the filename is normalized to the language's module-naming rule — Python and Rust use
   underscores (`session-lifecycle` → `test_session_lifecycle.py`), TypeScript keeps the hyphens
   (`session-lifecycle.test.ts`). The spec determines the test file's location and name — an agent
   never invents a test path. The functional vs integration distinction is a **per-test marker**,
   never a directory; the marker form is defined in the per-language testing policy.

   **Contract-defining artifacts are not tested — the artifact is the spec.** A thin shim whose
   behavior is its own declaration — a command wrapper, a git filter, a fixed-response tool — is not
   tested: a test of it would only restate the contract it declares (the literal-echo anti-pattern).
   Test feature behavior bound to a spec, never a declaration. If such a tool grows branchy
   decision-logic worth catching, that is a signal to simplify the tool or move the logic into a
   tested unit — not to add a test to the tool. **This holds when the fix to a bug is itself such a
   declaration (for example, declaring a required dependency): there is no reproduction test, because
   a test would only restate the declaration.**

### Coverage and drift

8. **Coverage is measured against the scenario inventory** — scenarios bound ÷ total — not by
   source-to-test file mapping. Bind `@critical`-tagged scenarios first; the remainder is a measured
   backlog. A scenario bound by two tests is a duplicate; a binding to a non-existent scenario is an
   orphan; both fail the coverage check.

   Every scenario a plan will bind is reserved at prepare, on `main`, before the build-time binding
   act — the claim is that the scenario is enclosed by a pending marker owning the binding for the
   drafting todo. A newly authored scenario carries the claim as its own `planned:<slug>` block; an
   existing live-and-unbound scenario is claimed by wrapping its `#### UC-…` block in a
   `planned-change:<slug>` that restates the scenario unchanged, which the delivery fold clears so the
   scenario stays live and the test binding becomes its permanent record. A scenario enclosed by no
   pending marker is unclaimed. Because prepare authors directly to `main`, a concurrent prepare reads
   the existing claim and either reuses the scenario by reference — adding no second binding — or
   authors a distinct scenario; markers never nest, so two todos claiming the same region serialize
   via `telec todo update <later> --after <earlier>`. The duplicate this rule forbids is prevented at
   its source rather than only caught once both tests have landed.

9. **A changed scenario forces its bound test to be revisited.** When a scenario's Gherkin changes,
   the bound test is re-derived from the new contract before the change is done (rule 10) — the
   spec-drift guard. This is carried by the change process and the reviewer, not by an automated
   fingerprint: a behavior contract cannot change without its test being revisited.

### The change process

10. **Behavior changes start in the spec, then flow spec → test → code.** The Product Owner edits
    the feature snippet; the build agent reads the current spec against the existing bindings and
    works the delta:
    - **Removed scenario** → delete its bound test, then the code it exclusively covered.
    - **Added scenario** → bind it (write the test), confirm it fails, implement, confirm it passes.
    - **Changed scenario** → update the bound test to the new contract, confirm it fails against
      current code, update the code, confirm it passes.
      The agent derives the delta by reading the spec against what is already bound; the reviewer
      checks the delta was honored.

### Spec structure (so scenarios have stable identity)

11. A feature spec's scenarios live under a `### Use cases` heading. A scenario with a stable id is a
    `#### UC-<area><n>:` subsection containing exactly one fenced Gherkin block; ids are unique within
    a spec. A Gherkin block not yet under a `#### UC-` header is an **anonymous scenario** — the
    id-assignment backlog, worked down as scenarios get bound. This structure is upheld by the
    authoring discipline and the reviewer.

### Assertion craft (all languages)

12. **String content is never asserted by literal, substring, prefix, suffix, or pattern.** Three
    permitted moves: a **snapshot** of any emitted string (the snapshot is the contract); a narrow
    **non-empty guard** at boundaries where accidental erasure is the failure mode (asserts that
    something was produced, never what); and a **named-constant identity** comparison when behavior
    turns on identity (production and test import the same constant). Assert exceptions by type, not
    message text; assert states by typed/enum fields. Rendered prose that realizes a spec scenario is
    snapshot-covered at the renderer's boundary. Agent-facing advisory output — formatter
    instructions, prompts, guidance strings — is its own declaration: a snapshot of it is permitted
    but never mandated, and it is never asserted by content. A change to such prose is not a coverage
    gap; the only forbidden outcome is a content-grading assert. A bare string literal used as test
    input or fixture data is unremarkable and stays inline — it is not a magic-string violation, and
    the closed-vocabulary/constant discipline does not reach it. When a forbidden content assertion
    must be fixed, the remedy is a **snapshot** or, only when behavior turns on identity, the
    **imported production constant** — never a constant defined inside the test to hold the expected
    value. Hoisting a literal into a test-local constant is not a remedy but literal-echo;
    "extract this string into a constant" is therefore not a valid review finding against a test.
13. **Rejected as primary assertions:** logger/metric/trace calls and log text; native
    struct/model/config shapes that are not an external wire contract; private helpers; constructor
    or dependency-injection wiring; mock-call echoes where the mocked thing is not an architectural
    boundary; literal-echo (rebuilding an expected value from source-visible literals); primitive
    side-effects (only that a file/record was created) with no application logic exercised;
    passthrough-only forwarding that is not itself the contract; parametrized / table-driven bodies
    (one representative input per behavioral path, one named test per path); and redundant coverage
    of the same behavior across files.
14. **One behavioral path per test.** A case is a code path, not an input row. Tests are
    deterministic, independent, and named so the name is a behavioral specification. Every test
    answers: _what real bug in our code would this catch?_
15. **Snapshot approval is a conscious act.** A snapshot's regression value is realized only when its
    diff is read at update time — CI never updates snapshots, so a person or agent does, and a blind
    `--snapshot-update` converts the test into theater and forfeits the guarantee. The approval is
    cheap and bounded: confirm the diff is the delta you intended, then sniff for anomalies — empty or
    missing blocks, unfilled placeholders, stale interpolations, garbled content. It does not require
    re-deriving the value from the producing code or re-reading the rules that shaped it; intent-match
    plus anomaly-sniff is the whole act. When a snapshot changes, state in the report what changed and
    why it is intended — an unexplained snapshot delta is an unreviewed one.

## Rationale

- Agents reliably honor a specified contract but reliably produce poor tests and poor coherence
  across a codebase. So tests exist to preserve coherence and yield a measurable, un-gameable
  coverage signal against the human-owned contract — not to catch bugs the agent would not have made.
- Binding to tech-agnostic, human-authored Gherkin removes agent discretion over what to assert,
  makes coverage objective and non-redundant, and lets the same scenarios bind to a future
  re-implementation — a migration parity oracle.
- Where no compiler enforces unit-level correctness, an agent-authored unit test grades its own code
  and drifts to green-theater; the product is orchestration glue where functional tests catch the
  real failures.

## Scope

- All repositories and all behavior-changing work, in every language. Language-specific idioms,
  runners, file paths, and the unit-test exception are defined in the per-language testing policy.

## Enforcement

- Binding completeness — bound / unbound / duplicate / orphan against the scenario inventory — is
  enforced; bindings are expressed and checked per-language.
- Spec structure (the `### Use cases` section, well-formed unique `#### UC-` ids, one Gherkin block
  per id) and binding completeness are upheld at review.
- Per-language checks enforce the unit-test stance for each language.
- The reviewer judges binding honesty: does the test drive the real system for its scenario without
  mocking the thing under test.

## Exceptions

- A compiled language whose type system enforces unit-level correctness keeps colocated unit tests,
  per its language policy. The no-agent-unit-test rule applies only where no compiler provides that
  guarantee.
