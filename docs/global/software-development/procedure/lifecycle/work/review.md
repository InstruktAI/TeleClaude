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

- `todos/{slug}/requirements.md` exists (or `bug.md` for bug fixes). For ad-hoc items created via `telec todo from-main`, requirements and implementation plan are stubs — see "Ad-hoc items" below.
- `todos/{slug}/implementation-plan.md` exists (unless bug fix or ad-hoc item).
- `todos/{slug}/quality-checklist.md` exists and includes Build/Review sections (unless bug fix).
- Build phase completed for the slug.

## Steps

### 1. Establish review scope

If no slug provided, select the first item with phase `active` in `state.yaml` that lacks `review-findings.md`.

Read:

- `todos/{slug}/requirements.md` (or `bug.md` for bug fixes)
- `todos/{slug}/implementation-plan.md`
- `README.md`, `AGENTS.md`, and `docs/*` for project patterns

Use merge-base to focus the diff:

```bash
git diff $(git merge-base HEAD main)..HEAD --name-only
git diff $(git merge-base HEAD main)..HEAD
```

Orchestrator-managed files (`todos/roadmap.yaml`, `todos/{slug}/state.yaml`) are part of the task context. Do not raise findings for changes in these files unless review scope explicitly includes planning/state edits.

### 2. Completeness checks

- Ensure all implementation-plan tasks are checked (`[x]`). Unchecked tasks -> REQUEST CHANGES.
- If `deferrals.md` exists, confirm each deferral is justified. Unjustified deferrals -> REQUEST CHANGES.

### 3. Run review lanes

Run lanes in parallel where possible. Each lane produces findings with severity levels.

| Aspect     | When to use                 | Skill                      | Task                                                              |
| ---------- | --------------------------- | -------------------------- | ----------------------------------------------------------------- |
| scope      | Always                      | _(reviewer direct)_        | Verify delivery matches requirements — no gold-plating, no gaps   |
| code       | Always                      | next-code-reviewer         | Find bugs and pattern violations                                  |
| paradigm   | Always                      | _(reviewer direct)_        | Paradigm-fit assessment (see below)                               |
| principles | Always                      | _(reviewer direct)_        | Principle violation hunt (see below)                              |
| security   | Always                      | _(reviewer direct)_        | Check for secrets, injection, auth gaps, info leakage (see below) |
| tests      | Always                      | next-test-analyzer         | Evaluate behavioral value, weak-test anti-patterns, and coverage  |
| errors     | Always                      | next-silent-failure-hunter | Find silent failures                                              |
| types      | Types added/modified        | next-type-design-analyzer  | Validate type design                                              |
| comments   | Code changed                | next-comment-analyzer      | Check accuracy of comments on changed code                        |
| logging    | Always                      | next-code-reviewer         | Enforce logging policy; reject ad-hoc debug probes                |
| demo       | Always                      | _(reviewer direct)_        | Verify demo.md has real executable blocks (see below)             |
| docs       | CLI, config, or API changed | _(reviewer direct)_        | Verify help text, config surface, README reflect changes          |
| simplify   | After other lanes pass      | next-code-simplifier       | Simplify without behavior changes                                 |

### Lane execution gate

Before proceeding to lane details, verify every lane whose trigger condition is met
("Always" or conditional match) was executed. Each executed lane must produce a
section in `review-findings.md` — even if no issues were found. A lane section that
says "No findings" proves the lane ran. A missing lane section means the review is
incomplete — stop and execute the missing lane before writing the verdict.

#### Ad-hoc items (from-main)

Items created via `telec todo from-main` have stub requirements and implementation plans.
For these items, the scope and demo lanes are not applicable — skip them and note "Ad-hoc
review" in the findings header. All other lanes remain mandatory. The reviewer should focus
on whether the delivered code meets project quality policies.

### 4. Lane detail reference

#### Scope verification

The delivery must match the requirements — nothing more, nothing less.

- Every requirement in `requirements.md` has a corresponding implementation.
- No unrequested features, extra CLI flags, additional API endpoints, or premature configurability.
- No gold-plating: the builder implemented what was asked, not what they thought would be nice.

Scope violations are **Important** findings. Significant unrequested features are **Critical**.

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
3. A test that only proves configuration or props were passed through unchanged.
4. A test that only proves a mock was called with the same data the test itself constructed.
5. A test that would stay green if the real branching logic were replaced with a constant.

Severity guidance:

- Weakening or deleting prepare-delivered spec assertions -> **Critical**.
- Missing tests for new or changed behavior -> **Important**.
- New or changed behavior covered only by weak tests -> **Important**.
- A changed test that cannot answer the "what bug would this catch?" question -> **Important**.
- Supplemental cleanup suggestions where a strong behavioral test already exists -> **Suggestion**.

Missing tests for new behavior are **Important** findings.
Missing browser-smoke verification for browser-based frontend changes is an **Important** finding.

#### Demo artifact review

Read `todos/{slug}/demo.md` (or `demos/{slug}/demo.md`). For each executable bash block, cross-check against the actual implementation:

- Do the commands, flags, and subcommands actually exist in the codebase?
- Does expected output match what the code would produce?
- Does the demo exercise features that were actually implemented — not planned, not old behavior?

**Findings:**

- Block uses nonexistent flags or commands -> **Critical**.
- Demo is shallow, expected output is fabricated, or demo could pass validation while being functionally wrong -> **Important**.

**No-demo marker (`<!-- no-demo: reason -->`) is a hard gate:**

- Valid only for pure internal refactors with zero user-visible behavior change.
- If delivery touches CLI, TUI, config, API, or messaging -> no-demo marker is invalid -> **Critical**.
- "Requires live terminal interaction" is never valid — the AI presenter can drive TUI, Playwright, and APIs.
- If justification is legitimate, explicitly note acceptance in findings.

#### Documentation and config surface check

When the delivery changes CLI subcommands, config keys, API endpoints, or user-facing behavior:

1. CLI help text updated for new/changed subcommands.
2. `config.sample.yml` updated if new config keys introduced.
3. Teleclaude-config spec updated if config surface changed.
4. README or relevant docs reflect current behavior.
5. Breaking changes documented.

Missing documentation updates are **Important** findings. Missing config surface updates are **Critical** (agents depend on accurate config specs).

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
3. The fix is localized (for example: typing, docs/help text, plan/demo
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

When `todos/{slug}/bug.md` exists, use it as the requirement source instead of `requirements.md`. Verify:

1. Fix addresses the symptom described in `bug.md`.
2. Root cause analysis is sound.
3. Fix is minimal and targeted.
4. Investigation and documentation sections are complete.
5. A reproduction test exists — the bug was reproduced as a test before the fix.
6. The reproduction test passes after the fix.

Missing reproduction test for a bug fix is a **Critical** finding. All other review lanes still apply.

### 6. Write and commit findings

Write unresolved findings to `todos/{slug}/review-findings.md`.

Verdict rules — **verdict is arithmetic, not judgement:**

- Count unresolved Critical findings. Count unresolved Important findings.
- If either count > 0: verdict is `REQUEST CHANGES`.
- If both are 0: verdict is `APPROVE`.
- Suggestion findings may remain unresolved under `APPROVE`.
- The reviewer must not invent categories ("non-blocking", "accepted", "deferred
  to follow-up") to reduce the count and achieve APPROVE. The only way to reduce
  the count is to resolve the finding: auto-remediate it, or investigate and
  determine it is invalid with evidence. Overall delivery quality does not
  override individual finding severity.

If all findings were remediated inline, record a short "Resolved During Review"
section so the caller can trace what changed.

Commit all files in the worktree. Do not edit `state.yaml` in the reviewer session
(the orchestrator records the verdict), but do commit any orchestrator-written
changes alongside review findings. Report summary and verdict to the caller.

## Report format

```
REVIEW COMPLETE: {slug}

Critical:
- [Issue]

Important:
- [Issue]

Suggestions:
- [Issue]

Verdict: APPROVE | REQUEST CHANGES
```

## Outputs

- `todos/{slug}/review-findings.md` with structured severity sections.
- A commit containing review findings (and any allowed checklist updates).
- Verdict reported to orchestrator for phase-state recording.

## Recovery

- If review cannot be completed, report the blocker with context and stop.
