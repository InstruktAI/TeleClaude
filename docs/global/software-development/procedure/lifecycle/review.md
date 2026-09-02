---
description: Shared review execution contract for lanes, evidence, citations, severity, verdict arithmetic, and reviewer separation.
---

# Review — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/definition-of-done-lanes.md
- @~/.teleclaude/docs/software-development/policy/process-change-authority.md
- @~/.teleclaude/docs/general/policy/human-involvement-recording.md
- @~/.teleclaude/docs/software-development/policy/quality-predicate-registry.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/principle-violation-hunt.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/silent-failure-audit.md
- @~/.teleclaude/docs/software-development/principle/module-depth.md
- @~/.teleclaude/docs/software-development/policy/substrate-anchoring.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md

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

Review attempts to falsify the target's claims against its governing contract.
It does not brainstorm risks, maximize findings, improve the design, or
prescribe speculative defenses.

A finding is valid only when all four hold:

1. it cites the specific policy, Definition of Done line, principle, or spec it
   violates — a principle is a citeable clause;
2. it establishes, from current authoritative sources and the reviewed
   artifact, that the cited clause applies here;
3. it explains the contradiction causally — what the target does and why that
   conflicts with the clause;
4. it states the closure condition within the frozen scope, without
   prescribing implementation.

An observation missing any one of these is an **investigation lead**, not a
finding: it cannot block, never enters remediation, requires no producer
response, and cannot enlarge current work. Report it under its own heading or
route it separately; a lead that silently becomes remediation is the failure
this contract exists to prevent. Absence of a specific prohibition is never a
finding's basis when a principle covers the case; "the design feels wrong" is
not a finding under any citation.

Use this format:

```text
Severity — Policy: <citation>
Location: <file:line>
Violation: <one sentence stating what the target does that the cited rule forbids>
Closure: <the condition that resolves it, within the frozen scope, stated without prescribing implementation>
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

Write the complete structured report to the review artifact named by the
invoking procedure on every pass, including a clean pass, before stamping the
verdict. The report is the durable audit record for that pass: it includes every
executed lane, the arithmetic verdict, and the `Why No Issues` evidence when
required. The verdict stamp binds the current review target digest and the
current report digest; neither the transcript nor an earlier report substitutes
for that artifact.

### 6. Bound the convergence

Scope is frozen before review begins: the authorized intent, and the
independently reviewed architecture or plan where one exists, form the fixed
denominator every finding is judged against. Remediation closes valid findings
within that scope; a valid omission finding may add material, but scope growth
is semantic and line count proves nothing either way.

A round completes when the single reviewer issues one verdict bound to one
frozen target digest; incomplete attempts and messages do not count, and
remediation starts only after that verdict. Rounds are counted by reviewed
revisions. The first round is one complete discovery pass over the frozen
target. A remediation round closes existing findings and inspects the
remediation delta. A new finding on a remediation round is admissible only when
it is remediation-induced, or newly observable because the target changed. A
finding that was observable in the discovery pass and is raised later is the
reviewer's incompleteness: it halts the loop for reassessment instead of being
appended to the producer's work.

When the cap is reached, the loop halts and its cause is classified — ambiguous
contract, failed remediation, unstable target, or incomplete or noisy review.
If the unapproved target is already present on an authoritative shared surface,
only its reviewed paths are restored to the last approved target digest, and a
newly introduced target is withdrawn from that surface. An isolated or
versioned target is frozen unchanged. The target history, findings, and
classification remain evidence. Any later attempt begins from the approved
baseline as fresh bounded work.

Findings and their dispositions persist with the reviewed work. A fresh reviewer
derives independently before reading prior dispositions, then reconciles; a
continuing reviewer works from its own ledger. A disposition reopens only on
changed substrate or material new evidence; re-filing it otherwise is reviewer
incompleteness.

## Outputs

- A complete, current review artifact covering every applicable lane, even when
  the pass is clean.
- An arithmetic `APPROVE` or `REQUEST CHANGES` verdict bound to that artifact
  and the reviewed target.

### Report format

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

## Recovery

If the target, applicable contract, or required evidence cannot be resolved,
report the blocker to the invoking procedure and stop. Do not narrow the review
to what happens to be available.
