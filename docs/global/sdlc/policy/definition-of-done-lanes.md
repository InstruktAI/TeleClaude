---
description: The review lanes — the review-time enforcement of the Definition of Done.
  Defined once here; referenced by the build reviewer, the commit reviewer, and anticipated
  by the planner.
visibility: public
---

# Review Lanes — Policy

## Required reads

- @~/.teleclaude/docs/sdlc/procedure/lifecycle/work/principle-violation-hunt.md
- @~/.teleclaude/docs/sdlc/procedure/lifecycle/work/silent-failure-audit.md
- @~/.teleclaude/docs/sdlc/policy/quality-predicate-registry.md
- @~/.teleclaude/docs/sdlc/policy/definition-of-done.md

## Rules

The review lanes are the focus areas a code review runs. Each lane is the
**review-time enforcement of a Definition of Done gate** (or, for the scope lane,
the requirement contract). They are defined once here and consumed by:

- `sdlc/procedure/lifecycle/work/review-build` — the build reviewer, which **executes** the applicable lanes.
- `sdlc/procedure/lifecycle/work/review-commits` — the commit reviewer, which executes the same lanes; that procedure resolves the scope lane's intent basis.
- `sdlc/procedure/lifecycle/prepare/plan-draft` and `.../prepare/review-plan` — the planner and plan reviewer, which **anticipate** the lanes (the plan must pre-satisfy what build-review will check).

Severity tiers, citation rules, the lane execution gate, and verdict arithmetic
live in the review procedure, not here — this catalog defines _what each lane
checks and the authority it answers to_, not how a review is run.

Every lane finding cites the contract the reviewed artifact violates. A finding
that prescribes new functionality, instrumentation, or subsystems beyond the
approved intent enlarges the horizon and is invalid
(`sdlc/policy/preparation-artifact-quality`, §Evidence does not
reallocate ownership); a genuine intent gap is reported as an investigation
lead, never encoded as a blocking demand.

Run lanes in parallel where possible. Each lane produces findings with severity levels.

A project-scope testing ruling (for example a test moratorium) supersedes the
tests lane and every per-criterion named-test demand in Scope verification for
that project, per `general/policy/conflict-resolution`: reviewers there judge
each criterion against the changed code and approved intent. The integrator's
later log judgment is not a per-criterion proof source. Demanding or rewarding
forbidden test authorship violates the project ruling. All other lanes apply
unchanged; in every project without such a ruling this catalog applies in full.

| Lane                    | Reference                                                                              | Task                                                                                                                                                                             |
| ----------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| scope                   | § Scope verification                                                                   | Verify delivery matches PRD intent — no gold-plating, no gaps                                                                                                                    |
| code                    | § Code quality review; `code-quality-practices`, `design-fundamentals`                 | Find bugs and pattern violations                                                                                                                                                 |
| ownership               | § Domain ownership review; `domain-ownership`                                          | Verify every domain rule is implemented by its single owning context and crossed only through a published contract                                                               |
| paradigm                | § Paradigm-fit assessment                                                              | Check data flow, component reuse, pattern consistency, forward-migration of owned data                                                                                           |
| principles              | § Principle violation hunt; `principle-violation-hunt`                                 | Structural violation hunt against design principles                                                                                                                              |
| intelligence-boundaries | `principle/intelligence-boundaries`                                                    | Find code that classifies, scores, judges, or auto-edits free-text content semantics                                                                                             |
| security                | § Security review                                                                      | Check for secrets, injection, auth gaps, and repository-privacy leakage                                                                                                          |
| tests                   | § Test coverage check; `quality-predicate-registry`                                    | Evaluate behavioral value, weak-test anti-patterns, and coverage                                                                                                                 |
| errors                  | § Error handling review; `silent-failure-audit`                                        | Find silent failures and inadequate error handling                                                                                                                               |
| types                   | § Type design review (when types added/modified)                                       | Validate type invariants, encapsulation, and enforcement                                                                                                                         |
| comments                | § Comment accuracy review                                                              | Verify comments are accurate, non-stale, and earn their place                                                                                                                    |
| logging                 | § Logging review                                                                       | Enforce logging policy; reject ad-hoc debug probes                                                                                                                               |
| docs                    | § Documentation and config surface check (when CLI, config, or API changed)            | Verify help text, config surface, README, and affected doc snippets reflect changes                                                                                              |
| doc-hygiene             | § Doc-snippet hygiene (when a `docs/**` snippet or any directive-text surface changed) | Verify changed snippet bodies state present-tense contract — no narration; verify changed directive text was the author's to write and states the reality wanted from its reader |
| simplify                | § Simplification review (after other lanes pass)                                       | Simplify without behavior changes                                                                                                                                                |

### A verdict and its lane scores are written together

Lane scores describe the state the verdict is issued against, so a verdict that
changes without its scores being re-run leaves a document asserting both
"unmet" and "approved" — and the reader cannot tell which half is current. When
a review approves work it previously rejected, the lanes are re-scored against
the corrected state in the same act; carrying forward the earlier scores under a
new verdict is a defect in the artifact regardless of whether the fixes were
real.

The verdict is written by the reviewer alone. An author recording its own
approval into the review artifact after applying fixes — however faithfully it
applied them — destroys the one property the artifact exists to carry, which is
that someone other than the author looked.

### Every review pass leaves current, bound evidence

Every preparation and build review writes its complete phase-specific report
before stamping a verdict, including a pass with zero findings. The stamp binds
the current target digest and current report digest together with the verdict,
caller session, and timestamp. An absent report, an absent binding, or a later
rewrite of either target or report leaves the verdict non-current and cannot
satisfy a review gate.

This binding proves that a versioned report existed for the reviewed target; it
does not prove the report's analysis was intellectually sound. Reviewer
separation, lane completeness, citations, and verdict arithmetic remain
judgment gates.

### Lane coverage is reported in full — no silent skips

Lane coverage is a complete checklist, not a best-effort scan. The planner, the
plan reviewer, and the build reviewer each report **one line per lane in the
catalog above** — marking it satisfied (naming how), unmet (a finding), or `N/A`
(with reason). A catalog lane with no line is itself a defect: silence is not
coverage.

Deliverable-producing lanes (tests, security, docs, config, browser/UI, ADR) are
reported by naming the artifact and the task or diff that delivers it. The lanes
that produce no artifact — `code` Duplication, `paradigm` Component reuse, and
`simplify` — are reported against the changed surface itself: the plan's
`referenced-paths` at plan time, the diff at build time. A task or change that
re-derives, mirrors, or re-implements logic an existing symbol already provides,
instead of extracting it once and reusing it, is a duplication finding on this
checklist.

### A restriction answers what it no longer covers

A diff that narrows an existing rule — removing a condition it matched, replacing
a set it read with a smaller one, or tightening the state that triggers it —
states what the rule no longer catches. This holds whether the rule is expressed
in code or in directive text, and it holds however sound the narrowing is: the
reviewer's question is not whether the change is correct but what coverage it
withdraws. A restriction whose author cannot name what it drops is reviewed as a
scope change, not as the correction it was offered as.

The question is asked by every lane against its own subject; it adds no lane and
no separate report line.

### Lane catalog

#### Scope verification

**Authority:** the intent basis the invoking procedure resolves. For a lifecycle
review it is the requirement contract — `prd` (feature) or `input` (change/bug),
or the `implementation-plan`'s _Intent & scope_ for a `--plan` `change` with no `input`.

The reviewed changes must satisfy the resolved authorized intent within the
named review target — nothing more, nothing less (for lifecycle work, see
`sdlc/concept/approved-intent-artifact`).

For each criterion in that intent basis, produce a `Scope verification` entry in
the report surface named by the invoking procedure (`review-findings.md` for a
lifecycle review):

1. Identify the authoritative source and quote the criterion.
2. Identify the specific reviewed change that delivers it (file, function, line range).
3. Explain, in one sentence, how that change satisfies it.
4. Where the project opts into tests, name the scenario-bound test and the
   concrete production-code mutation it catches under the testing policy.

Findings:

- Criterion not delivered by any reviewed change → **Requirement-Violation** (see Severity schema in the review procedure).
- Criterion partially delivered — some criteria sub-points addressed, others silently dropped → **Requirement-Violation**. A delivery that narrows a criterion's scope is as broken as one that omits it.
- In a project that opts into tests, the named test would pass on a broken
  implementation → **Requirement-Violation**.
- Unrequested feature (no criterion drives it) → **Critical**.
- For a change/bug, a behavioral delta the intent does not call for — including one introduced alongside a necessary change, or one resolving a forced decision by new behavior where established behavior or human escalation was the path → **Critical**.
- Directive text authored where the intent called only for its removal or correction → **Critical**. Replacing an instruction the intent condemned with a different instruction of the author's own devising is a behavioral delta wearing the shape of the requested edit; the one-line diff and the honest commit subject are what let it pass. `general/policy/documentation-discipline` owns which text is directive.
- Gold-plating (scope creep beyond the authorized intent) → Important.

A reviewer cannot approve while any Scope verification entry is missing its
reviewed change or satisfaction analysis. In a project that opts into tests, the
entry also needs its test and killing mutation.

#### Code quality review

**Authority:** DoD §2 (Code Quality) + `code-quality-practices`, `design-fundamentals`.

Systematically check changed code for bugs, pattern violations, and structural anti-patterns. Read `code-quality-practices` and `design-fundamentals` before starting.

For each changed file, evaluate:

1. **Bug detection** — Logic errors, null/undefined handling, race conditions, off-by-one errors, resource leaks. Focus on code paths that can produce wrong results or crash.
2. **Contract fidelity** — Do call sites honour the contract of the functions they call? Are preconditions met? Are return values handled correctly?
3. **Pattern violations** — Does the code follow the established patterns in adjacent code? Import conventions, error handling style, naming, module structure.
4. **Duplication** — Is logic copy-pasted where it should be extracted? Is an existing utility ignored?
5. **Unnecessary complexity** — Premature abstraction, over-engineering, dead code, unreachable branches, abstractions with a single consumer.
6. **Language-policy ownership** — For every changed code file, load the applicable language policy and apply its rules for string ownership, closed vocabularies, typing, and tooling. Findings cite that language owner. A generic review rule never substitutes its own language construct or command.
7. **Shared-resource cost** — Where the change makes a path wait on a lock, transaction or other resource that unrelated work also holds, name those other holders and what they do while holding it, whether the wait is bounded, and whether the outcome reaches each caller within that caller's deadline. Judge it from the change, the resource's other holders in the code, and the callers the path serves.
8. **Executable logic in carriers** — In every changed file whose purpose is configuration, declaration, orchestration or convention, whatever its format, each executable body it carries — a Make recipe, a workflow run block, a build step, a hook — is a single delegation line to a script or module. Declarative content is unaffected, and a file may hold several such bodies; a body that branches, loops, computes or parses is code in the wrong place (`sdlc/policy/no-inline-logic`).

Only report findings with high confidence — quality over quantity. Each finding must name the file, line range, the specific violation, and a concrete fix.

Severity guidance:

- Bugs that produce wrong results or crash → **Critical**.
- Contract violations at boundaries → **Critical**.
- A wait on a shared resource that can outlast its caller's deadline → **Critical**.
- Pattern violations that increase maintenance cost → **Important**.
- Executable logic in a carrier file → **Important**.
- Unnecessary complexity or duplication → **Important**.
- Minor style inconsistencies that do not violate a cited policy → **drop the observation; it is not a finding**.

#### Domain ownership review

**Authority:** `sdlc/policy/domain-ownership` and the project's
context map and domain specs.

For every changed behavior, invariant, state transition, validation rule, and
ubiquitous-language decision:

1. Name its single bounded-context owner from domain meaning and reason to
   change, not from caller, adapter, scheduler, runtime host, storage location,
   todo boundary, current file, or adjacent pattern.
2. Verify the implementation sits in the correct architectural layer inside
   that owner. Correct layer placement in the wrong context does not pass.
3. Verify every consumer crosses through the owner's published command, query,
   event, or type and does not restate, specialize, validate, default, recover,
   or mutate the owner's rule locally.
4. Verify cross-cutting coordinators and design surfaces own only the
   relationship, never the participating domain behavior.
5. Verify every changed spec, plan, or design states only its own context's
   rules. A contract that dictates a mechanism another context's design owns —
   which checks a gate runs, how a peer selects or authorizes — is a consumer
   restating that owner's rule in the contract layer. Code that conforms to such
   a contract carries the same defect.

Wrong-context placement, duplicated owner policy, host-as-owner reasoning, and
direct bypass of an owner's published contract are **Critical**, including when
a reviewed contract called for them. Unresolved
ownership is also Critical; reviewers do not infer an owner from existing
placement. This is semantic reviewer judgment. Mechanical dependency checks
may expose crossings, but no path-name or prose scanner determines ownership.

#### Paradigm-fit assessment

**Authority:** `design-fundamentals`, `backward-compatibility-hygiene`, `substrate-anchoring`.

Check whether the implementation follows existing codebase paradigms:

1. **Data flow**: Does it use the established data layer, or bypass it with inline hacks?
2. **Component reuse**: Does it reuse and parameterize existing components, or copy-paste them?
3. **Pattern consistency**: Does it follow patterns established by adjacent code?
4. **Schema evolution**: For data the project owns (persisted state, config, artifacts), does it migrate the stored shape forward, or carry a backward-compatibility branch for an old shape? The contract for owned data is forward-migration (`backward-compatibility-hygiene`, Owned internal data); a version-tolerance branch in domain code is the violation, not the workaround. Any change to the field set of an owned persisted or serialized model — adding a field, renaming a field, removing a field, or tightening one to required — is itself a schema change: the diff must include the forward-migration step that rewrites existing records to the new shape **and** a golden-fixture test that loads an old-shape record through the new model. A field-set change with no migration is a defect that surfaces only when a pre-change record is read back, never in the change's own tests. The trap is a rename that does not bump the schema version: affected records are already stamped at the latest version, so a version-gated `vN → vN+1` hop never runs on them — the migration must normalize them unconditionally.

5. **Structural ratchet**: Does the delivery leave the modules and seams on its
   change path no worse, and carry its ratchet disposition — a preparatory
   deepening commit, or a recorded deepening candidate with the reason for
   deferral (`definition-of-done` §2)? The reviewer blocks an introduced or
   worsened violation. It may challenge a deferral only by disproving its
   stated reason, never by substituting the reviewer's preferred refactor.
   Untouched debt outside the change path is never a finding.

6. **Existing path**: Before reading the change's own reasoning, establish how
   this system already reaches the same kind of outcome for a comparable case.
   Does the change take that path, or does it assemble a new mechanism beside
   it, even one whose every part reuses an existing module
   (`substrate-anchoring`)? An undeclared parallel is **Critical**. A declared
   divergence whose reason does not hold is **Important**.

Paradigm violations are **Important** at minimum. An introduced or worsened
violation on the change path is Important. Where the reviewer establishes
structural debt on the change path, absence of a preparatory deepening or a
reasoned deferral is Important; a delivery whose change path carries no
structural debt owes no disposition. Copy-paste of a parameterizable component
is Important. Bypassing the data layer is Critical. A backward-compatibility branch on owned data — version tolerance smeared through domain logic where a forward migration is the contract — is Critical. A field-set change to an owned persisted or serialized model that ships with no forward-migration, or with no old-shape golden-fixture test, is **Critical** — it delivers a record the current model can no longer read.

#### Principle violation hunt

**Authority:** the documented design principles (`principle-violation-hunt`).

Systematic check of changed code against documented design principles, with fallback detection as the most prominent target. The reviewer performs this directly (not delegated) because it requires full context.

Use the `principle-violation-hunt` procedure for detailed hunt criteria.

**Severity baseline:** Unjustified fallback paths are **Critical**. A fallback is justified only when UX literally dies without it, documented in a code comment at the fallback site.

#### Intelligence-boundaries

**Authority:** `principle/intelligence-boundaries`.

Find code that classifies, scores, judges, evaluates, or auto-edits free-text
content semantics — intelligence that belongs in an agent's briefing, not in code
the agent wraps. Consult `principle/intelligence-boundaries` for the detection
patterns and the defining test.

The lane's question is positive: list every decision the change makes about
free text and name where each executes. A judgment moved from an agent into
code is the finding. That a change removes an agent, invokes fewer agents, or
makes work "mechanical" is never a compliance argument; it is the exact shape
the principle warns against.

#### Security review

**Authority:** DoD §5 (Security) + `security-awareness`.

Check the diff for security issues against the Definition of Done security gates:

1. **Secrets**: No hardcoded credentials, API keys, tokens, or passwords in the diff.
2. **Sensitive data in logs**: Log statements must not emit PII, tokens, or credentials.
3. **Input validation**: User input and external data validated at boundaries.
4. **Injection**: No untrusted data interpolated into shell commands, SQL, templates, or another executable language.
5. **Authorization**: Access control checks present where required.
6. **Error messages**: Stack traces and internal paths not exposed to end users.
7. **Repository privacy**: Inspect every changed text surface — including documentation,
   comments, examples, tests, fixtures, configuration samples, artifacts, and
   generated-looking files — for environment-derived computer or host names, usernames,
   internal addresses, absolute machine-local paths, session or transcript exports, debug
   dumps, or private topology. Operational documentation uses placeholders and points to
   the runtime discovery surface instead of copying current values.

Repository privacy is semantic reviewer judgment. Do not automate it with regex, keyword,
denylist, or other prose scanning; credential secret scanning remains a separate mechanical
control. Security violations are **Critical** findings.

#### Test coverage check

**Authority:** DoD §3 (Testing) + `sdlc/policy/testing` and the per-language testing policy.

This lane applies the atomic rejection predicates in
`sdlc/policy/quality-predicate-registry` and the doctrine in
`sdlc/policy/testing` plus the relevant per-language testing
policy. The registry owns the rejection predicate and required evidence; the
testing policies own the behavioral model and language idioms. Read and apply
both; do not re-derive or restate either here.

This lane fires **always**, not only when test files changed. Read any changed or newly added tests directly and map each to the production behavior it claims to protect — never infer test value from file names, coverage output, or suite counts. The presence of tests is not evidence of adequate review.

Apply the policy, not a per-function reflex:

- **Coverage is the scenario inventory, not "every new function."** A coverage finding requires an **unbound feature-spec scenario this change delivers**. Absent such a scenario — platform-internal machinery, or a contract-defining / thin artifact (the artifact is its own spec) — there is nothing to bind, and "missing tests" is **not** a finding.
- **Never request an agent-authored unit test where the applicable language testing policy forbids one.** If branchy internal logic genuinely warrants coverage, the finding is to **extract it to a scenario-bound functional test** — never "add a test here."
- **Spec-delivered test specs:** every assertion from the spec-delivery commit must still exist; a removed or weakened assertion is a **Critical** finding (diff the spec-delivery commit against the final state).
- **Weak tests are findings even when coverage exists.** Apply every weak-test anti-pattern the testing policy enumerates — the policy owns the full list; do not re-list it here.
- **Browser / web UI changes** must include Playwright smoke evidence from build.

Before crediting any test as meaningful coverage, name the concrete production-code mutation it kills: a single plausible wrong implementation of the behavior under test — a flipped condition, a dropped branch, a stubbed-out value — that turns this test red. State it explicitly; a vacuous or unnameable answer ("it covers the feature") is itself the weak-test finding. A test that stays green on the broken implementation does not count, no matter what it asserts — the assertion is observing a projection of the output that cannot see the property the behavior actually changed.

- Reject **meta-tests that statically scan production source or file inventories** to enforce a structural rule. A structural rule must be placed at the **strongest layer that can express it**, in this order — never lower when a higher one applies:
  1. **Make the illegal state unrepresentable** in the applicable language's type or signature surface.
  2. **Use the language's native type checker or linter** when a type cannot express the invariant but a native rule already covers it.
  3. **Use a custom lint guard** only when 1–2 provably cannot express the invariant, with a one-line justification of why no type or native check suffices.
  4. **Never** use a runtime test for a static property.
     A test paying per-cycle cost for a static property — or a `tools/lint` guard duplicating what a type would enforce — is the anti-pattern, not the fix.
- Reject **placeholder or xfail "spec" tests** that document intended-but-not-yet-implemented behavior. The spec-anchored model has no waiting-to-flip tests: an unbound scenario is tracked as coverage backlog by the coverage tool, not as a test sitting in `tests/`. A test exists only to bind a scenario it currently satisfies. Also verify each binding is honest — it drives the real system for its scenario without mocking the thing under test — and that no in-scope spec has orphan or duplicate bindings (`tools/lint/spec_coverage.py` can be run on demand to surface these).

- Reject **an unreserved scenario binding** at plan-review anticipation. Every scenario a plan declares it will bind is reserved on `main` at prepare — enclosed by this todo's pending `planned` or `planned-change` marker. A plan that declares a binding for a scenario enclosed by a different in-flight todo's pending marker is a **Requirement-Violation**: the scenario is already reserved, and a second binding is the cross-worktree duplicate the integration content gate would otherwise catch. The check is structural — scenario id to owning slug — and `tools/lint/binding_reservation.py` surfaces the collisions on demand.

- Reject **refactor-leftover existence checks** that assert a removed source path remains absent. Git history records what was removed; the test adds nothing.
- Reject **filesystem-inventory snapshots** whose captured value is a collection of paths produced by walking a directory tree. The snapshot pins the implementation's output layout, not behavior. If the behavior is "no files written to this root," assert that condition directly without snapshotting an inventory.

- Apply `TQ-04` from `sdlc/policy/quality-predicate-registry` to configuration and default assertions. `TQ-04` is the single rejection predicate and evidence contract.

- Reject **unit tests wearing the language's `functional` label** — a marker is self-asserted by the author and proves nothing. A test fails this check when it enters at an internal symbol that is not the behavior's real surface and fakes that symbol's in-process collaborators, or when it patches in-process non-boundary collaborators so the real chain never runs, or when its value is a return-value, construction-default, or config-literal assertion. Verify against `sdlc/concept/functional-test-boundary` that the test drives a real entry surface and fakes only the process or network line. Naming style is not the disqualifier; the real surface and collaboration boundary decide. This is a review judgment against the definition; no path check or scanner decides it, and treating one as the enforcement manufactures false assurance.
- Reject **tests that pin a superseded owned-data shape** — a test asserting an old config, artifact, or persisted-aggregate schema the code is meant to migrate forward (`backward-compatibility-hygiene`, Owned internal data). It makes the dead compatibility path load-bearing and resists its own deletion. Schema-evolution coverage belongs in the migration's `vN → vN+1` golden-fixture test asserting the current shape — never in a test that locks the old one in place.
- Review snapshot deltas in the PR with the same weight as code deltas. Read each snapshot diff and confirm it matches the change's stated intent. An unreviewed or unjustified snapshot update is a finding.
- A test file appearing on the project's string-assertion exemption list is acceptable only if the current PR does not touch that file. If the PR touches a listed test file, the file must be migrated to snapshots in the same change and removed from the exemption list.

Treat the following as common weak-test patterns:

1. A test that only proves a string still reads the same.
2. A test that only proves an object still has fields visible in the source literal.
3. A test that only proves configuration, props, or data were passed through unchanged.
4. A test that only proves a primitive artifact or side effect exists after a direct library call.
5. A test that only proves a mock was called with the same data the test itself constructed.
6. A test that would stay green if the real branching logic were replaced with a constant or trivial passthrough.

Severity guidance:

- Weakening or deleting prepare-delivered spec assertions -> **Critical**.
- Missing tests for new or changed behavior -> **Important**.
- New or changed behavior covered only by weak tests -> **Important**.
- A changed test that cannot answer the "what bug would this catch?" question -> **Important**.
- A `functional`-marked test that drives an internal non-boundary symbol or fakes in-process collaborators so the real chain never runs -> **Important** (the coverage is illusory; **Critical** when it replaces or weakens a prepare-delivered spec assertion).
- Supplemental cleanup observations where a strong behavioral test already exists -> **drop the observation; it is not a finding**.

Missing tests for new behavior are **Important** findings.
Missing browser-smoke verification for browser-based frontend changes is an **Important** finding.

#### Error handling review

**Authority:** DoD §8 (Observability) + `silent-failure-audit`.

Audit all error handling paths in the diff for silent failures, inadequate logging, and inappropriate fallback behavior. Use the `silent-failure-audit` procedure for the systematic approach.

Key targets:

1. **Empty catch blocks** — absolutely forbidden.
2. **Broad exception catches** — `catch (Exception)` or `except Exception` that hide unrelated errors.
3. **Log-and-continue** — logging an error but continuing execution without surfacing to the caller.
4. **Silent defaults** — returning `[]`, `None`, `0`, or fallback values on error without logging.
5. **Optional chaining abuse** — `?.` chains that silently skip operations that should fail visibly.
6. **Retry without escalation** — retry loops that exhaust attempts without informing the caller or user.

For each handler, ask: would a developer debugging this 6 months from now have enough information in the logs to find the problem?

Severity guidance:

- Silent failures (error swallowed, no log, no user feedback) → **Critical**.
- Broad catches that could mask unrelated errors → **Critical**.
- Poor error messages or missing context in logs → **Important**.
- Unjustified fallback behaviour → **Important** (or **Critical** if it masks data corruption).

#### Type design review

**Authority:** DoD §2 (Code Quality) — type design.

When the diff introduces or modifies types, data models, or record structures, evaluate the type design quality.

For each type, assess:

1. **Invariant identification** — What consistency rules, valid state constraints, or relationship constraints does the type encode? Are they explicit or implicit?
2. **Encapsulation** — Are internals hidden? Can invariants be violated from outside the type?
3. **Invariant enforcement** — Are invariants checked at construction? Are all mutation points guarded? Can invalid instances be created?
4. **Usefulness** — Do the invariants prevent real bugs? Are they aligned with domain requirements?

Common anti-patterns to flag:

- Anemic domain models with no behaviour (just data bags with external logic).
- Types that expose mutable internals.
- Invariants enforced only through documentation, not code.
- Missing validation at construction boundaries.
- Types with too many responsibilities.
- **Closed vocabulary not modeled as the language-mandated closed type** — a finite set of related values remains expressible as scattered literals at production call sites instead of through its single semantic owner. The applicable language policy defines the construct. Test inputs and fixtures remain under the testing policy.
- **Invariant policed by a scanner a type could own** — an invariant enforced by an external lint, guardrail, regex, or meta-test when the language's type or schema system could make the illegal state unrepresentable. The scanner is the band-aid; the type is the fix. See the enforcement-placement order in the test-coverage lane.

Severity guidance:

- Types that allow invalid states to be constructed → **Important**.
- Closed vocabulary represented outside the applicable language's required closed type → **Important** (**Critical** when divergent inlined literals have already caused a defect).
- Invariant enforced by a lint/guard a type could make unrepresentable → **Important**.
- Exposed mutable internals on shared types → **Important**.
- Missing construction validation on boundary types → **Important**.
- Minor encapsulation improvements that do not violate a cited policy → **drop the observation; it is not a finding**.

#### Comment accuracy review

**Authority:** DoD §6 (Documentation) — comments.

Verify that comments on changed code are factually accurate, non-stale, and earn their place. A wrong comment is worse than no comment.

For each comment on changed code:

1. **Verify accuracy** — Cross-reference every claim against the actual implementation. Do described parameters, return types, and behaviour match the code?
2. **Check for staleness** — Does the comment describe the code as it was before this change, not as it is now? Stale comments after a refactor are a common source of confusion.
3. **Evaluate value** — Comments explaining "why" are valuable. Comments restating what the code obviously does are noise. Comments describing the past ("used to", "removed", "was previously") belong in git history, not in code.
4. **Flag misleading elements** — Ambiguous language, outdated references, assumptions that no longer hold, TODOs that are already done.

Severity guidance:

- Factually incorrect comments that will mislead future readers → **Important**.
- Stale comments that describe pre-change behaviour → **Important**.
- Commented-out code → **Important**.
- Redundant comments that restate obvious code → **Important** (per Comments policy: comments must earn their place; restating WHAT the code does is forbidden).

#### Logging review

**Authority:** DoD §8 (Observability) + `sdlc/policy/observability` (level and content) + the applicable language logging policy (mechanism).

Verify that changed code follows the observability contract and its language realization. Load both before reviewing.

Check for:

1. **Correct log levels** — every changed statement carries the level `sdlc/policy/observability` assigns to its event class. Misleveled logs pollute or hide signal.
2. **Structured format** — Log statements must use the structured fields and interpolation rules defined by the applicable language logging policy.
3. **Sensitive data** — No log statement emits what the observability policy's never-log rules exclude.
4. **Ad-hoc debug probes** — Direct standard-output calls or temporary logging added during development must be removed or converted according to the applicable language logging policy.
5. **Identifier integrity** — Identifiers appear at full value, per the observability policy.
6. **Boundary coverage** — Significant operations are observable at the points the observability policy's boundary rule names.

Severity guidance:

- Sensitive data in logs → **Critical**.
- Ad-hoc debug probes left in production code → **Important**.
- Wrong log levels that hide errors or pollute the production level → **Important**.
- Missing boundary logging for significant operations → **Important** (per DoD §8 Observability: logging at key boundaries is required).

#### Documentation and config surface check

**Authority:** DoD §6 (Documentation) + `documentation-first-development`.

When the delivery changes CLI subcommands, config keys, API endpoints, or user-facing behavior:

1. CLI help text updated for new/changed subcommands.
2. `templates/config.yml` updated if new config keys introduced.
3. Teleclaude-config spec updated if config surface changed.
4. README or relevant docs reflect current behavior.
5. Breaking changes documented.

**Doc-snippet reflection (always, not only interface changes):** when the delivery
changes or adds a documented behavioral contract, the corresponding doc snippet
(spec / principle / policy / concept / ADR) must be updated to match — through a pending carrier
(`general/procedure/doc-snippet-authoring`) for lifecycle work, or directly for
an in-place correction. A behavioral delta whose contract snippet was not updated, with no
recorded `doc_impact_none: <reason>`, is a finding. This is the build/commit-review
backstop to the plan-review documentation hard gate, so a forgotten snippet update
cannot reach delivery.

**No account- or installation-specific literals in committed configuration
(every diff that changes a committed configuration or declaration file):** a committed configuration or declaration file carries
only what holds for everyone who clones the repository. A value that belongs to
one account, organization, installation or machine — an account, App,
installation or repository identity, an owning company or person, a host, a
path, a credential — is authored as a whole environment reference
(`${NAME}` or `${NAME:-default}`), with the value in that installation's
environment. Such a literal in a committed configuration file is **Critical**,
whoever wrote it and whatever the delivery's subject: a fork or another
installation inherits it as if it were its own.

**Work-phase doc freeze (build reviews only):** the doc layer is authored at
prepare on `main` and folded at integration; the work phase executes a frozen
contract. A lifecycle work-phase diff (slug worktree) that touches `docs/**` is
**Critical** — out of jurisdiction regardless of the edit's quality or size. The
correct route for a doc need discovered mid-build is the kickback path back to
prepare, never an in-worktree doc edit. This rule does not apply to commit
reviews of `main`-branch doc commits, which are prepare-side or in-context doc
work by design.

Missing documentation updates are **Important** findings. Missing config surface updates are **Critical** (agents depend on accurate config specs).

#### Doc-snippet hygiene

**Authority:** `general/principle/intent-first-documentation` + `general/policy/adr-discipline` + `general/policy/snippet-value-contract` (full anti-pattern list, not Narration alone) + `general/policy/referencing-doc-snippets` (citation form) + `general/policy/agent-facing-text` (reader framing) + `sdlc/policy/process-change-authority` + `sdlc/policy/language-policy-ownership`.

Conditional lane — fires whenever the diff touches a `docs/**` snippet **or any
directive-text surface** (below). The DoD docs lane above checks that docs _exist
and reflect the change_; this lane checks that the changed prose is _clean_ and
_the author's to write_. A snippet body states present-tense intent and contract —
nothing else. This is a reviewer judgment, not an automated grader: code that
scores free-text prose quality would itself violate
`principle/intelligence-boundaries`, so the reviewer reads the prose and applies
the rule. Tooling may **route** a diff into this lane by locating changed string
literals on the surfaces named below; it never grades what those literals say.

**Scope.** Audit the **changed regions** (added/modified lines and their enclosing
section), the snippet's **frontmatter**, and any **newly-added or delivered**
planned block (`&lt;!-- planned:slug --&gt;`), planned-change block
(`&lt;!-- planned-change:slug --&gt;`), or companion (`<stem>.<slug>.md`). Do NOT
re-audit unchanged regions of a snippet the diff merely touched elsewhere —
pre-existing narration outside the change is not this change's finding. A
delivered planned, planned-change, or companion body is fully in scope, because
delivery touches it.

**Use-case changes.** Apply `sdlc/procedure/feature-spec-authoring` to each
changed representation, including a retirement. Verify the retained stakeholder
outcome or necessary invariant at its actual owner, together with affected
identities, references, acceptance bindings and pending contracts. Preserving a
requirement does not mean copying implementation traces into prose
(`general/policy/snippet-value-contract`).

**Co-tenant edits.** A diff may change a region enclosed by a different slug's
pending marker — a structural fact tooling may route on. Judge which edit it is.
_Aligning_ that slug's text with its own moved intent is legitimate: read that
slug's intent artifact and the diff, and ask only whether the edit preserves that
intent. Not its code, not its plan in full. _Superseding_ it — the changed text
becomes false when the editing slug delivers — must be attributable to the
editing slug and must not land ahead of it; an unattributed supersession folds
with the owning slug and ships a change its own review never saw.

**Directive-text surfaces.** Agent-facing directive text lives outside `docs/**`
as often as inside it, so this lane's trigger is the content, not the path. A
directive-text surface is any string a run of the system prints or hands to a
reader that names a next move: build-target and script output (`Makefile`,
`tools/**`), CLI help and error text, printed gate and guidance blocks, command
and skill bodies, and dispatched-worker briefs. `general/policy/documentation-discipline`
owns the directive-versus-descriptive cut; apply it rather than re-deriving one.
On these surfaces the narration anti-patterns below do not apply — they are
snippet-body rules — and three checks do:

- **Authorization.** The changed directive text is one the approved intent called
  for. Text authored where the intent called only for removal or correction is
  the `scope` lane's finding (below), raised there.
- **Process-change.** Directive text that alters a process-layer behavioral
  contract is governed by `sdlc/policy/process-change-authority`:
  verify the agent-owned mechanism is covered by a current or pending contract
  and independently reviewed, and classify only its underlying consequence
  under `general/policy/human-contract`.
- **Reader framing.** The changed text states the reality wanted from the role
  its load path reaches (`general/policy/agent-facing-text`). Text that names
  acts that role excludes is this check's finding, unless it is that policy's
  counter for an act the reader is already invited to take.

**Procedure composition check.** When a changed procedure carries root
frontmatter, or its subscriptions or Required reads changed, the reviewer reads
the frontmatter of every other procedure in the corpus, pending ones included,
and applies the composition step of `general/procedure/doc-snippet-authoring`:
its role is declared by no other procedure, an event or trigger whose
responsibility a standing role already carries is a route in that role's entry
procedure, and none of its own sub-procedures is a Required read. Each finding
is **Important**. The check reads across todos because each delivery's own
review sees only its own procedure.

**Frontmatter liveness check.** `delivered_by` is authorship provenance, not a
dispatch gate. The reviewer checks frontmatter shape and stale delivered
relationships against `general/spec/snippet-authoring-schema`:
a known slug whose todo is already delivered is a finding, because delivery
should have folded it. A slug absent from the local todo store is not a finding:
todos are machine-local, so a git-carried pending snippet routinely names a
delivery that lives elsewhere or has already been hard-purged after reconciliation.
Do not use `telec todo show <slug>` 404 as evidence that a pending snippet is
undeliverable.

**Companion re-sync check.** When a commit edits a live parent `<stem>.md` and
a non-empty pending companion `<stem>.<slug>.md` exists, the reviewer reads
both the parent diff and the companion. The commit is flagged unless the
companion is re-synced in the same change or the diff records a deliberate
coordination decision. An empty companion retires its parent and carries no
body to re-sync. This is reviewer judgment over the changed files, not an
automated free-text grader.

**Process-change check.** When changed prose alters a process-layer behavioral
contract, apply `sdlc/policy/process-change-authority`: verify
the before/after guarantee and material reason are recorded, the mechanism is
covered by the changed contract, and ordinary independent review applies. A
control relaxation additionally requires explicit approval from a reviewer
with no stake in the work it unblocks. Return to the human only for an
underlying consequence in the closed human lane; asking for human approval of
the mechanism is itself a finding. Descriptive edits that preserve behavior do
not trigger this check.

**Language-owner check.** When changed generic sdlc prose or an
agent-executable example prescribes syntax, a type construct, library, runner,
marker, filename, compiler capability, checker, or exact command, flag it as
wrong-owner placement unless comparison or routing is the snippet's subject.
The concrete rule belongs in the applicable language policy and the generic
surface references that owner. Judge the meaning; do not build or rely on a
keyword scanner.

For each changed snippet body, flag the Narration anti-pattern in its four forms
(`snippet-value-contract` owns the full definition; do not re-derive it here):

1. **History in the body** — "replaces the v1 path", "is retired", "used to …",
   "previously named …". Belongs in git.
2. **Rationale in the body** — "because …", "this avoids …", "the reason we chose
   …". Belongs in the snippet's own Rationale section where its type has one, or is dropped.
3. **Inline provenance / coordination metadata** — "(delivered_by `<slug>`)",
   "Pending `<slug>`, …", a delivering slug named anywhere in body prose. Belongs
   in the `delivered_by` frontmatter field only.
4. **Future framing** — "will", "is planned", "the new surface is going to …",
   instead of a present-tense description of the intended shape.

For each changed snippet body, and for a baseline-manifest diff per item 8's
own trigger below, additionally flag the coherence anti-patterns
(`snippet-value-contract` owns the full definition; do not re-derive it here):

5. **Duplication without a citation, or a citation that misrepresents its
   owner** — the change restates a rule that another snippet already owns,
   rather than citing it (gist + backticked id, per
   `general/policy/referencing-doc-snippets`); or it does cite an id, but the
   gist claims something the cited snippet does not actually state, or the id
   names the wrong owner. A citation is not exempt from being read: when the
   diff adds or changes one, open the cited snippet and confirm the gist is
   true of it before clearing this item. A rule already stated in
   `general/policy/leadership` or `general/policy/human-contract` reappearing
   in full elsewhere, with or without an inaccurate citation attached, is this
   finding, not a style note. In a feature or domain spec this item's
   commonest form is **consumer restatement**: a use case, paragraph, or "or
   on another computer" variant whose `Then` clauses, read without actor and
   surface words, assert outcomes another context's spec decides
   (`general/policy/snippet-value-contract`, Consumer restatement). Open the
   owning context's spec — live, and pending via
   `telec docs get <id> --target <slug>`; an owner that is pending still
   exists — and apply the test: delete each `Then` clause the owner decides;
   what remains is this context's rule or nothing. The closure is removal (a
   live id retires per `sdlc/procedure/feature-spec-authoring`; a pending
   block is deleted) or a one-sentence pointer with the owner's id. The
   reviewer never requests that a consumer's use case be extended, completed,
   or made symmetric with the owner's rule; such a request assigns another
   context's behavior to the artifact under review
   (`sdlc/policy/preparation-artifact-quality`, §Evidence does not reallocate
   ownership) and is itself a defective finding.
6. **Section echo** — a required section restating another section of the same
   snippet, most often Enforcement re-listing Rules as "X is a violation," or
   Rationale restating a rule instead of naming the invariant it protects.
7. **Layer bleed** — a `principle` snippet carrying enforcement-grade rule
   clauses (trigger conditions, exact required phrasing, "is a violation"
   language) that belong in the policy operationalizing it; or a `policy`
   snippet carrying procedure mechanics (numbered execution steps) that belong
   in a procedure.
8. **Manual in the baseline** — new or expanded content in a snippet listed in
   any baseline manifest — a `baseline.md` at the global, domain, or project
   docs root — that only some sessions in that scope need: a declaration
   schema, a role-specific mechanics block, a lookup table. The reviewer checks
   whether the changed snippet is baseline-listed before applying this finding;
   it does not apply to on-demand snippets. This item's trigger is not only a
   changed snippet body: a diff that adds a row to any baseline manifest
   itself promotes that snippet to always-loaded even when the snippet's own
   body is untouched in the same commit. Read the promoted snippet's current
   content against this item when the manifest changes, not only when the
   snippet does.
9. **Restatement** — the changed region paraphrases source code, a
   configuration file, or workflow YAML instead of pointing to it. Check
   against the actual source the snippet claims to describe, not just against
   other snippets: a snippet is the wrong source of truth for what a codebase
   or config file already states.
10. **Value-copying** — the changed region repeats a value whose canonical
    home is code, configuration, a schema, or a runtime registry: a number,
    duration, limit, threshold, port, path, default, cadence, retention
    window, enum member, configured service, or registry entry. Naming the
    value's owner is fine; restating the value itself is not — it goes stale
    the moment the value moves, and nothing downstream catches it. An example
    of an artifact whose shape a schema, generator, or configuration file owns
    — a sample JSON or YAML document, generated file contents, captured command
    output — is this finding, not an illustration.
11. **Value test on a new snippet** — a snippet the diff adds must pass the
    value test in `general/policy/snippet-value-contract`: it answers a named
    future-agent question that a one-minute read of the relevant source, an
    already-loaded global policy or principle, the project's README, or an
    existing snippet does not already answer. A new snippet that fails is
    rejected or collapsed into a citation from an existing one.
12. **Prohibition priming** — the changed region names acts its reader's role
    excludes instead of stating the reality wanted from that role. The reader
    is the role the snippet's load path reaches; `general/policy/agent-facing-text`
    owns the definition and the counter for an invited act.

When the changed snippet is an ADR (`docs/local/adr/**`), additionally hold its
body to the ADR contract (`general/policy/adr-discipline`, `general/procedure/adr-authoring`
— "What an ADR is"):

5. **Forward ADR reference** — the body references a _later_ ADR, a decision that
   did not exist when this one was recorded. A backward reference to an _earlier_
   ADR is fine; only the forward direction is the violation, and the sole forward
   link is the older ADR's `## Status` supersession pointer.
6. **Work reference in an ADR** — the body names a todo, slug, `delivered_by`,
   delivery, or anything TBD, or the `adr` snippet carries a `delivered_by`
   frontmatter field or a companion file. An ADR records a decision, not work.
7. **Non-atomic ADR** — the record bundles more than one decision, or shards one
   cohesive contract across mutually-referencing ADRs (that contract belongs in a
   spec or domain doc).

Severity guidance:

- A **delivered** planned/companion body that carries future-framing or names its
  slug — now live and false in the standing contract → **Critical**.
- A forward ADR reference, or any work reference, in an ADR body → **Critical**
  (it falsifies the timeline or couples the record to ephemeral work).
- A non-atomic ADR, or a cohesive contract sharded across mutually-referencing
  ADRs → **Important**.
- Narration introduced or modified by this change in a live snippet body →
  **Important**.
- An edited parent snippet with an unsynced pending companion → **Important**.
- A snippet whose contract is correct but carries a stray rationale clause that belongs in its Rationale section or is dropped → **Important**.
- Duplication without a citation, or a new/changed citation whose gist
  misrepresents or misidentifies its owner, introduced or left uncorrected by
  this change, where the owning snippet already exists → **Important**.
- Consumer restatement — a use case, clause, or variant re-observing another
  context's decision — introduced or left uncorrected by this change →
  **Important**; a remediation that elaborates it instead of removing or
  pointing is a new **Important** finding.
- Layer bleed or Section echo introduced by this change → **Important**.
- New baseline-listed content that is Manual-in-the-baseline → **Important**,
  with the correct-shape note (move to an on-demand snippet, cite from the
  baseline snippet).
- Restatement of source code, config, or workflow YAML introduced or left
  uncorrected by this change → **Important**.
- Value-copying — a copied number, path, default, enum member, registry
  entry, or example of a schema-, generator-, or config-owned artifact —
  introduced or left uncorrected by this change → **Important**.
- A new snippet that fails the value test → **Important**.
- Prohibition priming introduced by this change, in a snippet body or on a
  directive-text surface → **Important**.
- A language-specific directive introduced in a generic snippet → **Important**;
  **Critical** when it conflicts with the applicable language owner or directs
  implementation through the wrong language mechanism.
- Pre-existing narration in a region this change did not touch → **drop the
  observation; it is not a finding** (the sweep owns it, not this review).

#### Doc-first paradigm check

**Authority:** `sdlc/policy/todo-creation-discipline` and `general/policy/documentation-discipline`.

Conditional lane. Triggers only for an ad-hoc commit review with no prepare artifacts; in a lifecycle work review the prepare phase owns doc reflection and this lane is a no-op.

For an ad-hoc commit review, establish whether the work qualified for its execution route under the intake contract. Commit size, file count and absence of prepare artifacts do not establish a violation.

Apply documentation obligations under `general/policy/documentation-discipline`; the documentation and doc-hygiene lanes assess their satisfaction. Ad-hoc delivery alone creates no feature-spec obligation, and global doctrine receives no use case.

A routing or documentation finding must satisfy the validity and closure rules in `sdlc/procedure/lifecycle/review`. Acknowledging or deferring a valid unresolved finding does not close it.

#### Simplification review

**Authority:** `design-fundamentals` / KISS + naming-clarity policy.

Run after all other lanes pass. Simplify changed code for clarity, consistency, and maintainability without changing behaviour.

Focus on:

1. **Unnecessary complexity** — Reduce nesting depth, eliminate redundant branches, flatten deeply nested conditionals.
2. **Redundancy** — Remove duplicate logic, consolidate related operations, eliminate dead code.
3. **Naming** — Improve variable and function names that don't communicate intent.
4. **Over-abstraction** — Remove abstractions with a single consumer. Three similar lines are better than a premature abstraction.
5. **Clarity over brevity** — Avoid nested ternaries; prefer explicit if/else or switch. Explicit code beats compact code.

Constraints:

- Never change what the code does — only how it does it.
- Do not combine too many concerns into single functions.
- Do not remove helpful abstractions that improve organisation.
- Scope to recently changed code unless explicitly instructed otherwise.

Simplification findings are **Important** severity. The simplify lane only flags concrete violations of KISS, design-fundamentals (over-abstraction, dead code), or naming-clarity policy — those are real maintainability concerns and they affect the verdict. If an observation cannot be tied to one of those policies, drop it; it is not a finding.

#### Bug-fix review

**Authority:** DoD §3 (Testing) + `debugging`. Conditional lane — fires when `kind == "bug"`.

When `kind == "bug"`, the `input` artifact is the bug report and the intent source (no `prd`),
sharpened by the `diagnosis` root cause. Verify:

1. Fix addresses the evidenced concern in `input`. Independently apply the debugging
   procedure's operation-outcome and failure-handling distinction to the diagnosis, then
   verify that the delivered behavior satisfies that concern under the diagnosed conditions.
   A recorded disposition or named follow-up does not establish delivery.
2. Root cause analysis is sound.
3. Fix is minimal and targeted: the smallest change that removes the diagnosed
   mechanism where the diagnosis places it — the reproducing site and, for a
   shared-contract root, every entry in its implementation census — plus a scenario-bound
   regression test where the project opts into test authorship — and **nothing
   else**. A delta that removes no part of the cause — guards against causes no
   diagnosis has established, extra validation layers, defensive defaults,
   fallbacks, adjacent refactors, new capability — is a **Critical** scope
   finding, even when the approved plan contains it: for a bug, `input` +
   `diagnosis` outrank the plan as scope authority. A family-census site outside
   that boundary owes nothing in this delivery (`sdlc/concept/defect-evidence`,
   family site).
4. Investigation and documentation sections are complete.
5. Where the project opts into test authorship, a reproduction test exists before
   the fix, binding either a pre-existing scenario or the single regression
   scenario the plan phase authored for this symptom (`policy/testing` rule 2,
   bug-lane exception). A contract-defining artifact with no bindable scenario
   needs no test (`sdlc/policy/testing`, "Contract-defining artifacts are not
   tested").
6. The reproduction test passes after the fix when item 5 requires one.
7. No scenario beyond the single regression scenario was authored, and beyond that scenario no new
   contract text shipped unless the diagnosed cause is a wrong documented contract — a fix that
   restores documented behavior carries `doc_impact_none`.

Missing reproduction test for a bug fix is a **Critical** finding only where the
project opts into test authorship and a bindable scenario exists. Demanding a
test under a no-tests ruling or for a fix that is itself a declaration is the
error, not the missing test.
All other review lanes still apply.

**Record-drift exception to item 2.** "Root cause analysis is sound" is not
Critical when all three hold at once:

1. The delivered code already satisfies every criterion in `input` — Scope
   verification is clean, nothing is left to build.
2. The only defect is that `diagnosis`/`investigation`/`implementation-plan`
   describe stale reality — a factual claim about what already happened (a
   root cause, a "this passes at HEAD" claim), not a wrong claim about what
   should have been built. Nothing about the approach was wrong.
3. Correcting the record implies no new functional or business decision — a
   rewrite of a description, not a re-derivation of intent.

When all three hold, the discrepancy is not Critical, does not force `REQUEST
CHANGES`, and its remedy is not kickback — record it as a `log` entry on the
todo instead: a factual note, never a
substitute for a real finding. Fail any one condition and this is a normal
finding at full severity: a root cause that is actually wrong — even when the
shipped fix happens to pass — does not qualify, nor does a fix that took a
wrong approach and merely happens to work. This is a narrow, checkable
exception for when delivery is already correct and only the trailing record is
wrong about it, not a general softening of root-cause rigor.

## Rationale

The lanes were embedded in the build-review procedure and re-described in the
plan reviewer, so two reviewers shared one copy and a third forked it — the lane
set could drift between "what the plan anticipates" and "what build-review
checks." Defining the lanes once, here, and having every reviewer and the planner
reference this catalog removes that drift.

Anchoring them under the Definition of Done makes the coupling explicit: each lane
is the review-time enforcement of a DoD gate (or the requirement contract for
scope). A new DoD gate should grow a lane; a lane should name the gate it answers
to. The per-lane **Authority** line is that binding, kept honest in one place.

Every lane asks whether a change is right, and a narrowing can be right at every
step while the rule it lands on ends up catching nothing. Correctness is
evaluated per claim; coverage is a property of the whole rule, and no per-claim
check reads it. That is why a narrowing arrives as its most persuasive form — a
fact correction, a field-name fix, a false premise removed — and passes review on
the strength of being true. Asking what a restriction withdraws is the only
question that reads the rule rather than the claim, and it costs one sentence
from an author who already knows the answer.

## Scope

Applies to build reviews, commit reviews, and prepare-plan review anticipation.

## Enforcement

Reviewers use this catalog as the lane inventory. Procedure snippets own execution
mechanics, verdict arithmetic, and report shape.

## Exceptions

None.
