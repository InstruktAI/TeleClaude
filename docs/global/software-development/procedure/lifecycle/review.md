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

The first review of a target is one complete discovery pass over the frozen
digest. A remediation review closes existing findings and inspects the
remediation delta. A new finding on a remediation review is admissible only
when it is remediation-induced, or newly observable because the target changed.
A finding that was observable in the discovery pass and is raised later is the
reviewer's incompleteness: it halts the loop for reassessment instead of being
appended to the producer's work.

Review passes are admitted within a review cycle. A valid substantive-drift
stamp ends the current cycle for every review target it invalidates and starts
a new cycle for each replacement target. The new cycle receives its ordinary
pass allowance and its own continuations; phase-wide counters, continuation
records, reports, and verdict evidence remain cumulative. Target or report
rewrites without a substantive stamp remain inside the current cycle and reset
nothing. This keeps the admitted-pass denominator grounded in the target it
governs (`general/principle/grounding`).

The v9-to-cycle migration has one explicit initialization rule for legacy
prepare-review state that cannot carry a cycle boundary it predates. When the
current verdict and evidence bindings are empty, a retained report exists, and
the current target was written after that report, the migration records the
cumulative round and continuation totals as the new cycle's offsets. Cycle-local
admitted rounds and continuations are totals minus those offsets, so both start
at zero while the cumulative values remain unchanged. It applies once during
upcycle. Other legacy shapes keep zero offsets. This favors another independent review over permanently blocking a
replacement-shaped target whose earlier cycle identity was never persisted
(`general/principle/grounding`).

<!-- planned-change:gut-review-cap-gate-and-continuation-stamp -->
When a review cycle reaches its applicable documented cap without closure, no further
automatic review starts. The orchestrator classifies the cause — ambiguous
contract, failed remediation, unstable target, or incomplete or noisy review —
from the current review evidence, and records the classification, the evidence
or changed approach that makes another attempt different, the responsible owner
and the closure condition. The producer's dispositions are part of that
evidence: a pass whose open findings are all standing rejections, re-filed
without changed substrate or material new evidence, was closed by the producer
and reopened by the reviewer, and the orchestrator classifies it as incomplete
or noisy review — never as failed remediation or an unstable target. Human
escalation follows the closed human lane, never the round count.

The classification decides what the orchestrator may do on its own authority.
Failed remediation whose remaining delta is small and grounded, and incomplete
or noisy review, each earn one continuation: the orchestrator admits exactly
one further pass through the continuation stamp, which persists the
classification and reason with the caller, and the machine dispatches a
reviewer that never reviewed this target before when the cause was the review.
An ambiguous contract earns no continuation; it goes to its decision owner. An
unstable target earns no continuation inside its current cycle; the producer
stops changing the target first. When the resulting evidence is stamped
substantive, that stamp starts the replacement target's new cycle under the
rule above. The reviewer of a continuation judges the corrected target independently;
authorization to continue is not approval of the target, and repeating an
unchanged attempt is not recovery.

A review cycle that reaches its cap a second time is assessed by a different
intelligence than the one that produced the work: the live coordinator. That
assessor reads the recorded classification and the review evidence and either
admits a further pass or routes the halt to its owner. With no coordinator live
there is no assessor: the halt stands unassessed, no further pass is admitted,
and the unresolved result is preserved with its agent owner. The
different-intelligence property does not hold on that branch, and the halt
reaches no one outside the closed human lane.
The orchestrator never assesses its own second continuation. It may write an admission the assessor
reached, and when it does it declares which assessor reached it; the record then names the assessor and
the writer separately, and that record is what an audit reads. The declaration is taken as given, like
every other relayed decision: nothing verifies that the named assessor assessed, and a false declaration
is answered by the durable record of the session that wrote it. If no grounded next
attempt exists, the unresolved result and its missing evidence are preserved
with an accountable agent owner; no one fabricates a verdict or resets a count
to conceal the halt.
<!-- change:gut-review-cap-gate-and-continuation-stamp -->
When a review cycle reaches its applicable documented cap, the count is reported
and nothing is refused. The report names the phase, the passes admitted, and the
threshold, and it instructs the orchestrator to dispatch an assist against the
loop. It is emitted once, on the pass that crosses the threshold, and not again;
the count keeps rendering afterwards. The instruction stands until an assist is
live — an orchestrator that did not act on the crossing pass is still obliged,
and is not reminded a second time.

The assist is an ordinary child of the orchestrator and lives for the loop. The
orchestrator sends it a line when a pass lands; it reads both sessions and the
review evidence itself, and says what shape the loop is in or says nothing. It
admits no passes, records no verdict and stamps nothing: what it produces is a
statement in its own session, and the orchestrator acts on what it read. Its
procedure is `software-development/procedure/lifecycle/assist`.

Nothing classifies the halt into a recorded vocabulary. Whether a loop is
converging, contested, moving under its reviewer, or stuck on a contract that
admits two grounded readings is what the assist says in its own words. A dispute
the assist judges to be in the contract rather than in the work leaves the loop
and goes to that contract's decision owner. Human escalation follows the closed
human lane, never the round count.

Crossing the threshold refuses nothing, so an orchestrator that ignores the
report and keeps dispatching is doing something no mechanism prevents. That
obligation is carried by this contract rather than by a refusal.
<!-- /planned-change:gut-review-cap-gate-and-continuation-stamp -->

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
