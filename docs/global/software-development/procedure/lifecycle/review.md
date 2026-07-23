---
description: Shared review execution contract for lanes, evidence, citations, severity, verdict arithmetic, and reviewer separation.
---

# Review — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/concept/reviewer.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done-lanes.md
- @~/.teleclaude/docs/software-development/policy/process-change-authority.md
- @~/.teleclaude/docs/software-development/policy/quality-predicate-registry.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/principle-violation-hunt.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/silent-failure-audit.md

## Goal

Apply one review contract to every review target. The invoking procedure owns
target resolution, the contextual contract available for scope review, and where
the result is delivered. This procedure owns the review lanes, evidence standard,
citation rules, severity schema, verdict arithmetic, and reviewer separation.

## Preconditions

- The invoking procedure has resolved the exact review target.
- The invoking procedure has named the applicable intent or governing contract.
- The target's complete changed-file surface is available.

## Steps

### 1. Execute every applicable review lane

Run every applicable lane defined in
`software-development/policy/definition-of-done-lanes`. The catalog owns each
lane's focus, severity guidance, and the Definition of Done gate or requirement
contract it answers to.

The invoking procedure determines whether the scope lane has a requirements
contract to trace. All other lanes run according to the catalog's trigger
conditions. The doc-hygiene lane runs whenever a doc snippet changes. The
doc-first paradigm lane runs for an ad-hoc commit review with no prepare
artifacts.

For the tests lane, independently re-prove every triggered `TQ-*` predicate.
Record evidence for each triggered predicate or a reasoned `N/A`. Evidence
supplied by the author directs attention but never substitutes for review proof.

Each executed lane produces a findings section, even when it has no findings.
A missing section means the review is incomplete: execute the missing lane
before producing a verdict.

### 2. Apply the quality gates

If the review produces no Important-or-higher findings, include a
`Why No Issues` section containing:

1. Evidence of paradigm-fit verification.
2. Evidence that the applicable contract was met: the prepared success criteria
   for a lifecycle build review, or the resulting behavior against its governing
   contracts for an ad-hoc commit review.
3. Evidence that copy-paste duplication was checked.
4. Evidence that security was reviewed.

For user-facing changes, record the observable behavior verified and the
evidence that confirms it. For browser-based changes, follow the applicable
Playwright smoke path when the environment allows it and record the observation.
When lifecycle build evidence exists, inspect the builder's recorded smoke path
as well. An unverified user-facing requirement is a finding.

### 3. Preserve reviewer separation

Reviewers evaluate; they do not author fixes. A reviewer does not edit source,
tests, documentation, configuration, generated files, or preparation artifacts.
The only writes a reviewer owns are the result surfaces explicitly named by the
invoking procedure.

Missing test coverage is reported, not patched by the reviewer. A finding that
shows prepared intent or a plan is wrong returns through the invoking
procedure's correction path; the reviewer never edits the prepared artifact.

### 4. Cite and classify every finding

Every finding cites the specific policy, Definition of Done line, principle, or
spec it violates. An observation without a discoverable citation is not a
finding.

Use this format:

```text
Severity — Policy: <citation>
Location: <file:line>
Violation: <one sentence stating what the target does that the cited rule forbids>
Fix: <one sentence stating the concrete change that brings it into compliance>
```

Use exactly three severity tiers:

- **Requirement-Violation**: a stated success criterion is absent, narrowed,
  partially delivered, or weakly verified.
- **Critical**: a bug, fallback violation, security issue, significant
  unrequested behavior, or weakened prepared assertion.
- **Important**: scope gold-plating, missing non-requirement coverage, paradigm
  or policy violation, or maintainability violation of a cited rule.

There is no fourth tier. Do not invent non-blocking, accepted, deferred,
suggestion, nit, or polish categories.

### 5. Derive the verdict arithmetically

- Any unresolved Requirement-Violation, Critical, or Important finding yields
  `REQUEST CHANGES`.
- Zero unresolved findings yields `APPROVE`.

Overall quality, prior patterns, merge state, review-round count, or the absence
of a fix loop never overrides this arithmetic. A count decreases only when
evidence establishes that the finding is invalid or resolved.

Return the structured findings and verdict to the invoking procedure. That
procedure alone owns whether the result is persisted to a todo or printed to a
caller.

## Report format

```text
REVIEW COMPLETE: <target>

Requirement-Violations:
- <finding with citation>

Critical:
- <finding with citation>

Important:
- <finding with citation>

Verdict: APPROVE | REQUEST CHANGES
```

## Outputs

- Structured findings covering every applicable review lane.
- An arithmetic `APPROVE` or `REQUEST CHANGES` verdict.

## Recovery

If the target, applicable contract, or required evidence cannot be resolved,
report the blocker to the invoking procedure and stop. Do not narrow the review
to what happens to be available.
