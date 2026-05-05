---
description: 'Review phase. Verify requirements, code quality, tests, and deliver verdict with findings.'
id: 'software-development/procedure/lifecycle/work/review'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
---

# Review — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/concept/reviewer.md
- @~/.teleclaude/docs/software-development/policy/code-quality.md
- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/linting-requirements.md

## Goal

Verify the implementation against requirements and standards, and deliver a binary verdict with structured findings.

## Preconditions

- `telec todo artifacts read {slug} requirements` exists (or `bug.md` for bug fixes). For ad-hoc items created via `telec todo from-main`, requirements and implementation plan are stubs — see "Ad-hoc items" below.
- `telec todo artifacts read {slug} implementation-plan` exists (unless bug fix or ad-hoc item).
- `telec todo artifacts read {slug} quality-checklist` exists and includes Build/Review sections (unless bug fix).
- Build phase completed for the slug.

## Steps

### 1. Establish review scope

If no slug provided, select the first item with phase `active` in `todo state (todos.db)` that lacks `review-findings.md`.

Read **in full, not only the diff**:

- `telec todo artifacts read {slug} requirements` (or `bug.md` for bug fixes) — the contract the delivery must satisfy.
- `telec todo artifacts read {slug} implementation-plan` — how the builder intended to satisfy the contract.
- `telec todo artifacts read {slug} plan-review-findings` and `spec-review-findings` — the per-criterion delivery analyses and spec-to-criterion mappings produced upstream. Use these as the ground truth for what the reviewer must verify against the code.
- `README.md`, `AGENTS.md`, and `docs/*` for project patterns.

The reviewer must be able to state, from the requirements text, what every requirement promises before running any lane. A review that reads only the diff passes scope-narrowed deliveries because the diff looks self-consistent. Reading requirements in full is the safeguard against that failure.

Use merge-base to focus the diff:

```bash
git diff $(git merge-base HEAD main)..HEAD --name-only
git diff $(git merge-base HEAD main)..HEAD
```

Orchestrator-managed files (`todos.db` roadmap, `todos.db` state) are part of the task context. Do not raise findings for changes in these files unless review scope explicitly includes planning/state edits.

### 2. Completeness checks

- Ensure all implementation-plan tasks are checked (`[x]`). Unchecked tasks -> REQUEST CHANGES.
- If `deferrals.md` exists, confirm each deferral is justified. Unjustified deferrals -> REQUEST CHANGES.

### 3. Run review lanes

Run lanes in parallel where possible. Each lane produces findings with severity levels.

| Lane       | Reference                                                                   | Task                                                             |
| ---------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| scope      | § Scope verification                                                        | Verify delivery matches requirements — no gold-plating, no gaps  |
| code       | § Code quality review; `code-quality-practices`, `design-fundamentals`      | Find bugs and pattern violations                                 |
| paradigm   | § Paradigm-fit assessment                                                   | Check data flow, component reuse, pattern consistency            |
| principles | § Principle violation hunt; `principle-violation-hunt`                      | Structural violation hunt against design principles              |
| security   | § Security review                                                           | Check for secrets, injection, auth gaps, info leakage            |
| tests      | § Test coverage check                                                       | Evaluate behavioral value, weak-test anti-patterns, and coverage |
| errors     | § Error handling review; `silent-failure-audit`                             | Find silent failures and inadequate error handling               |
| types      | § Type design review (when types added/modified)                            | Validate type invariants, encapsulation, and enforcement         |
| comments   | § Comment accuracy review                                                   | Verify comments are accurate, non-stale, and earn their place    |
| logging    | § Logging review                                                            | Enforce logging policy; reject ad-hoc debug probes               |
| docs       | § Documentation and config surface check (when CLI, config, or API changed) | Verify help text, config surface, README reflect changes         |
| simplify   | § Simplification review (after other lanes pass)                            | Simplify without behavior changes                                |

### Lane execution gate

Before proceeding to lane details, verify every lane whose trigger condition is met
("Always" or conditional match) was executed. Each executed lane must produce a
section in `review-findings.md` — even if no issues were found. A lane section that
says "No findings" proves the lane ran. A missing lane section means the review is
incomplete — stop and execute the missing lane before writing the verdict.

#### Ad-hoc items (from-main)

Items created via `telec todo from-main` have stub requirements and implementation plans.
For these items, the scope lane is not applicable — skip it and note "Ad-hoc
review" in the findings header. All other lanes remain mandatory. The reviewer should focus
on whether the delivered code meets project quality policies.
The build handoff is already complete before review starts: `from-main` auto-commits the
worktree handoff and emits `planning.todo_dumped` with `kind=built`, which the lifecycle
router turns into a detached `/next-work` dispatch. Review these items as delivered ad-hoc
work, not as manually dispatched build sessions waiting for another handoff step.

### 4. Lane detail reference

#### Scope verification

The delivery must match the requirements — nothing more, nothing less.

For each success criterion in every requirement, produce a `Scope verification` entry in `review-findings.md`:

1. Quote the criterion verbatim from `requirements.md`.
2. Name the specific code change in the diff that delivers the criterion (file, function, line range).
3. Name the test whose passing demonstrates the criterion is delivered.
4. State, in one sentence, how the code change and the passing test together satisfy the criterion.

Findings:

- Criterion not delivered by any code change in the diff → **Requirement-Violation** (see Severity schema below).
- Criterion partially delivered — some criteria sub-points addressed, others silently dropped → **Requirement-Violation**. A delivery that narrows a criterion's scope is as broken as one that omits it.
- Criterion delivered but the named test would pass even on a broken implementation → **Requirement-Violation**. Weak verification is not verification.
- Unrequested feature (no criterion drives it) → **Critical**.
- Gold-plating (scope creep beyond requirements) → Important.

A reviewer cannot approve while any Scope verification entry is missing or names "none" for the code change, test, or satisfaction analysis.

#### Code quality review

Systematically check changed code for bugs, pattern violations, and structural anti-patterns. Read `code-quality-practices` and `design-fundamentals` before starting.

For each changed file, evaluate:

1. **Bug detection** — Logic errors, null/undefined handling, race conditions, off-by-one errors, resource leaks. Focus on code paths that can produce wrong results or crash.
2. **Contract fidelity** — Do call sites honour the contract of the functions they call? Are preconditions met? Are return values handled correctly?
3. **Pattern violations** — Does the code follow the established patterns in adjacent code? Import conventions, error handling style, naming, module structure.
4. **Duplication** — Is logic copy-pasted where it should be extracted? Is an existing utility ignored?
5. **Unnecessary complexity** — Premature abstraction, over-engineering, dead code, unreachable branches, abstractions with a single consumer.

Only report findings with high confidence — quality over quantity. Each finding must name the file, line range, the specific violation, and a concrete fix.

Severity guidance:

- Bugs that produce wrong results or crash → **Critical**.
- Contract violations at boundaries → **Critical**.
- Pattern violations that increase maintenance cost → **Important**.
- Unnecessary complexity or duplication → **Important**.
- Minor style inconsistencies that do not violate a cited policy → **drop the observation; it is not a finding**.

#### Paradigm-fit assessment

Check whether the implementation follows existing codebase paradigms:

1. **Data flow**: Does it use the established data layer, or bypass it with inline hacks?
2. **Component reuse**: Does it reuse and parameterize existing components, or copy-paste them?
3. **Pattern consistency**: Does it follow patterns established by adjacent code?

Paradigm violations are **Important** at minimum. Copy-paste of a parameterizable component is Important. Bypassing the data layer is Critical.

#### Principle violation hunt

Systematic check of changed code against documented design principles, with fallback detection as the most prominent target. The reviewer performs this directly (not delegated) because it requires full context.

Use the `principle-violation-hunt` procedure for detailed hunt criteria.

**Severity baseline:** Unjustified fallback paths are **Critical**. A fallback is justified only when UX literally dies without it, documented in a code comment at the fallback site.

#### Security review

Check the diff for security issues against the Definition of Done security gates:

1. **Secrets**: No hardcoded credentials, API keys, tokens, or passwords in the diff.
2. **Sensitive data in logs**: Log statements must not emit PII, tokens, or credentials.
3. **Input validation**: User input and external data validated at boundaries.
4. **Injection**: No command injection (f-string in shell calls), SQL injection, or template injection.
5. **Authorization**: Access control checks present where required.
6. **Error messages**: Stack traces and internal paths not exposed to end users.

Security violations are **Critical** findings.

#### Test coverage check

This lane fires **always**, not only when test files changed. The absence of tests for new behavior is itself a finding. The presence of tests is **not** evidence of adequate review. Weak, tautological, prose-lock, or implementation-detail tests are findings even when coverage exists.

Read the changed or newly added tests directly. Map each one to the production behavior it claims to protect. Do not infer test value from file names, coverage output, or suite counts.

Before approving a changed or added test, answer all three:

1. What behavior, decision, or failure path does this test pin?
2. At what meaningful boundary is that behavior observed?
3. What real bug in **our** code would this test catch?

If you cannot answer those questions concretely, the test is weak and does not count as meaningful coverage.

- Are prepare-delivered test specs satisfied? Diff the spec delivery commit against the
  final state to verify no assertions were weakened or deleted.
- Every assertion from the spec commit must still exist. Removed or weakened assertion = **Critical** finding.
- New functionality must have corresponding tests.
- Edge cases and error paths must have coverage.
- Browser-based frontend or web UI changes must include Playwright smoke verification evidence from build.
- Tests must verify behavior, not implementation details.
- Reject tests whose primary assertion is prose, wording, formatting, or other human-facing text unless the exact token is execution-significant.
- Reject tests whose primary assertion is shape, signatures, keys, properties, constants, configuration echoes, or literal structure checks without proving decision logic or behavior.
- Reject tests that merely reconstruct an expected literal, structure, or payload from values already visible in the implementation or fixture and compare it back without proving semantics.
- Reject tests that only confirm a primitive side effect or passthrough occurred when no application-owned branch, validation rule, guard, or failure path was exercised.
- Reject tests whose only evidence is mock or spy interaction unless the interaction itself is the contract being tested at an architectural boundary.
- Reject tests that primarily verify framework, library, serializer, ORM, or other third-party behavior instead of our logic.
- Reject tests that pin private helpers, internal state, or refactor-sensitive implementation details when the same behavior can be checked at a public boundary.
- Reject characterization tests that pin observed behavior but provide no credible bug-catching value or mutation-sanity reasoning.
- Reject truthy or non-specific assertions that a trivially wrong implementation could satisfy.
- Reject redundant duplicate coverage across files when one test home is sufficient.
- Allow exact-string assertions only for execution-significant tokens/contracts.

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
- Supplemental cleanup observations where a strong behavioral test already exists -> **drop the observation; it is not a finding**.

Missing tests for new behavior are **Important** findings.
Missing browser-smoke verification for browser-based frontend changes is an **Important** finding.

#### Error handling review

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

When the diff introduces or modifies types, data models, or dataclasses, evaluate the type design quality.

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

Severity guidance:

- Types that allow invalid states to be constructed → **Important**.
- Exposed mutable internals on shared types → **Important**.
- Missing construction validation on boundary types → **Important**.
- Minor encapsulation improvements that do not violate a cited policy → **drop the observation; it is not a finding**.

#### Comment accuracy review

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

Verify that changed code follows the project's logging policy. Load the language-appropriate logging policy for the project before reviewing.

Check for:

1. **Correct log levels** — INFO for business-relevant events, DEBUG for successful outcomes with duration, WARNING for recoverable anomalies, ERROR for failures. TRACE for high-volume chatter. Misleveled logs pollute or hide signal.
2. **Structured format** — Log statements must use structured key=value format through the project's logging framework, not f-string interpolation or print statements.
3. **Sensitive data** — Log statements must never emit passwords, tokens, API keys, PII, or entire payloads.
4. **Ad-hoc debug probes** — Print statements, console.log, or temporary logging added during development must be removed or converted to proper structured logs at the correct level.
5. **Identifier integrity** — Never truncate UUIDs or session IDs in logs. Full values only.
6. **Boundary coverage** — Key operations (API calls, state transitions, external service interactions) should have logging at entry or completion, not both (avoid start/end pairs; prefer one line with duration).

Severity guidance:

- Sensitive data in logs → **Critical**.
- Ad-hoc debug probes left in production code → **Important**.
- Wrong log levels that hide errors or pollute INFO → **Important**.
- Missing boundary logging for significant operations → **Important** (per DoD §8 Observability: logging at key boundaries is required).

#### Documentation and config surface check

When the delivery changes CLI subcommands, config keys, API endpoints, or user-facing behavior:

1. CLI help text updated for new/changed subcommands.
2. `config.sample.yml` updated if new config keys introduced.
3. Teleclaude-config spec updated if config surface changed.
4. README or relevant docs reflect current behavior.
5. Breaking changes documented.

Missing documentation updates are **Important** findings. Missing config surface updates are **Critical** (agents depend on accurate config specs).

#### Simplification review

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

### 5. Quality gates

#### Zero-finding justification

If a review produces 0 Important or higher findings across all lanes, include a "Why No Issues" section in `review-findings.md`:

1. Evidence of paradigm-fit verification (which patterns were checked).
2. Evidence that requirements were met (which requirements were validated and how).
3. Explicit statement that copy-paste duplication was checked.
4. Evidence that security was reviewed.

A review with 0 findings and no justification is incomplete.

#### User-facing verification evidence

For deliveries with user-facing changes (UI, CLI output, interactive behavior), document:

1. What observable behavior was verified (or what could not be tested and why).
2. What evidence confirms the requirement is met.

For browser-based frontend or web UI changes, the reviewer must also:

1. Inspect the builder's recorded Playwright smoke path and result.
2. Follow the same Playwright smoke path during review when the environment allows it.
3. Record what the reviewer observed, or record the verification gap as a finding.

If user-facing verification is not possible, note the gap as a finding.

#### Reviewer auto-remediation

Default behavior is to act in place. If a finding is localized, high-confidence,
and can be validated within the same review pass, the reviewer should fix it
directly instead of handing it off.

Auto-remediation is appropriate when all of the following are true:

1. The fix does not change requirement intent or approved scope.
2. The fix does not introduce a new architectural decision.
3. The fix is localized (for example: typing, docs/help text, plan
   consistency, straightforward bug fix in touched area).
4. The reviewer can re-run the relevant checks and validate correctness.

Do not auto-remediate when uncertainty is high, product decisions are unresolved,
or changes require broad refactoring. Keep those findings unresolved and request
changes.

**Missing test coverage is never auto-remediated.** For new functionality, test
specs are expected to have been delivered upfront — a gap means the spec or build
phase fell short, not something the reviewer patches. For existing code, coverage
is characterization work that requires the builder's implementation context
(OBSERVE-ASSERT-VERIFY cycle). In both cases, report the finding and request
changes.

#### Bug fix review

When `telec todo artifacts read {slug} bug` exists, use it as the requirement source instead of `requirements.md`. Verify:

1. Fix addresses the symptom described in `bug.md`.
2. Root cause analysis is sound.
3. Fix is minimal and targeted.
4. Investigation and documentation sections are complete.
5. A reproduction test exists — the bug was reproduced as a test before the fix.
6. The reproduction test passes after the fix.

Missing reproduction test for a bug fix is a **Critical** finding. All other review lanes still apply.

### 6. Write and commit findings

Write the full findings artifact with `telec todo artifacts write {slug} review-findings "<content>"`.

#### Policy citation requirement

Every finding must cite the specific policy, Definition of Done line, principle, or
spec it violates. A finding without a citation is not a finding — drop it. The
citation is the anchor that prevents reviewer judgement from drifting toward leniency:
either the cited rule classifies the violation, or the observation does not belong
in the report.

Required format per finding:

```
Severity — Policy: <citation>
Location: <file:line>
Violation: <one sentence stating what the code does that the cited rule forbids>
Fix: <one sentence stating the concrete change that brings the code into compliance>
```

A `<citation>` names a discoverable artifact: a policy snippet ID, a DoD section
number, a principle name, or a spec section. "General code quality" is not a
citation. "Best practices" is not a citation. If you cannot name the rule, you
have an opinion, not a finding.

The citation also defeats the pre-existing-pattern dodge. Reviewer evaluates the
commit's resulting state, not its delta — if the code at this commit violates a
cited rule, the finding stands regardless of whether the violation predates this
commit. Touching a file is an enforcement opportunity.

#### Severity schema

Three severity tiers, highest to lowest:

- **Requirement-Violation**: the delivery does not satisfy a stated requirement's
  success criteria, whether through absence, partial delivery, or weak verification.
  A criterion that is silently narrowed, a test that would pass on a broken
  implementation, or a requirement whose delivery cannot be named — all are
  Requirement-Violation. **This severity cannot be deferred under any round count
  or closure procedure.** It is the highest severity and sits above Critical.
- **Critical**: bugs, fallback violations, security issues, significant unrequested
  features, weakening or deleting prepare-delivered spec assertions. Code is wrong
  or adds scope that was not requested.
- **Important**: scope gold-plating, missing tests for non-requirement behavior,
  paradigm violations, policy violations, maintainability violations of cited rules.

There is no fourth tier. The schema is intentionally three-deep so every cited
violation lands on a tier that affects the verdict. Observations that cannot be
classified into one of these tiers are not findings — drop them.

#### Verdict rules

Verdict is arithmetic, not judgement:

- Count unresolved Requirement-Violation findings. Count unresolved Critical findings.
  Count unresolved Important findings.
- If Requirement-Violation count > 0: verdict is `REQUEST CHANGES`. No exception.
  No closure procedure, no round-limit escape, no orchestrator override can change
  this. A requirement-gap is not an Important finding that can be rebranded.
- If Critical or Important count > 0: verdict is `REQUEST CHANGES`.
- If all three counts are 0: verdict is `APPROVE`.

The reviewer must not invent categories ("non-blocking", "accepted", "deferred
to follow-up", "suggestion", "nit", "polish") to reduce a count and achieve APPROVE.
The reviewer must not classify requirement-gaps as Important or Critical to make
them deferrable — requirement-gaps are Requirement-Violation by definition. The
only way to reduce a count is to resolve the finding: auto-remediate it, or
investigate and determine it is invalid with evidence. Overall delivery quality
does not override individual finding severity.

If all findings were remediated inline, record a short "Resolved During Review"
section so the caller can trace what changed.

Commit all files in the worktree. Stamp the verdict into todo state:
`telec todo stamp {slug} --verdict approve|changes_requested --phase build_review`.
The state machine derives phase from stamped primitives — if the reviewer does not
stamp, the orchestrator will be instructed to nudge the reviewer to do so.
Report summary and verdict to the caller.

## Report format

```
REVIEW COMPLETE: {slug}

Requirement-Violations:
- [Issue with citation]

Critical:
- [Issue with citation]

Important:
- [Issue with citation]

Verdict: APPROVE | REQUEST CHANGES
```

Each entry under each tier follows the citation format from the Policy citation
requirement above. A verdict line with no preceding tier sections (zero findings)
must be accompanied by the "Why no issues" justification per §5 Quality gates.

## Outputs

- `review-findings` todo artifact persisted via `telec todo artifacts write {slug} review-findings "<content>"`, with structured severity sections.
- A commit containing review findings (and any allowed checklist updates).
- Verdict reported to orchestrator for phase-state recording.

## Recovery

- If review cannot be completed, report the blocker with context and stop.
