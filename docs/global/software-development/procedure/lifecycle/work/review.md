---
description: 'Review phase. Verify PRD intent, prepared artifacts, code quality, tests, and deliver verdict with findings.'
needs_domain_baseline: 'True'
visibility: 'public'
---

# Review — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/concept/reviewer.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/principle-violation-hunt.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/silent-failure-audit.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done-lanes.md

## Goal

Verify the implementation against the PRD, prepared artifacts, and standards, and deliver a binary verdict with structured findings.

## Preconditions

- The approved intent artifact exists — `prd` for a `feature`, `input` for a
  `change`/`bug` (see `software-development/concept/approved-intent-artifact`).
- `telec todo artifacts read {slug} implementation-plan` exists (unless bug fix).
- `architecture` (thin doc-edit log) is readable when present and not skipped; consult the domain/design snippets it points to for technical context.
- `telec todo artifacts read {slug} quality-checklist` exists and includes Build/Review sections (unless bug fix).
- Build phase completed for the slug.

## Steps

First read the software-development principles as listed in the software-development baseline that apply to this work with `telec docs get`.

### 1. Establish review scope

If no slug provided, select the first item with phase `active` in `telec todo list` that lacks `review-findings`.

Read **in full, not only the diff**:

- `telec todo artifacts read {slug} prd` (or `bug` for bug fixes) — the product
  intent, success criteria, and scope the delivery must satisfy. If `prd` is
  absent but legacy `requirements` exists, read `requirements` as the legacy
  intent contract.
- `telec todo artifacts read {slug} architecture` when present — thin
  doc-edit index; consult the domain/design snippets it points to for
  technical context and constraints. The PRD's success criteria are the
  verification contract.
- `telec todo artifacts read {slug} implementation-plan` — how the builder intended to satisfy the contract.
- `telec todo artifacts read {slug} plan-review-findings` — the per-criterion delivery analyses produced upstream. Use as the ground truth for what the reviewer must verify against the code.
- `README.md`, `AGENTS.md`, and `docs/*` for project patterns.

The reviewer must be able to state, from the PRD success criteria, what every
required outcome promises before running any lane. A review that reads only the
diff passes scope-narrowed deliveries because the diff looks self-consistent.
Reading the PRD in full is the safeguard against that failure.

Use merge-base to focus the diff:

```bash
git diff $(git merge-base HEAD main)..HEAD --name-only
git diff $(git merge-base HEAD main)..HEAD
```

Orchestrator-managed files (`telec todo list`) are part of the task context. Do not raise findings for changes in these files unless review scope explicitly includes planning/state edits.

### 2. Completeness checks

- Ensure all implementation-plan tasks are checked (`[x]`). Unchecked tasks -> REQUEST CHANGES.
- If `deferrals.md` exists, confirm each deferral is justified. Unjustified deferrals -> REQUEST CHANGES.

### 3. Run review lanes

Run lanes in parallel where possible. Each lane produces findings with severity levels.

Run every applicable lane defined in the review-lanes catalog
(`software-development/policy/definition-of-done-lanes`, a Required read). The
catalog owns each lane's focus, severity guidance, and the DoD gate (or
requirement contract) it answers to. Trigger conditions: scope, code, paradigm,
principles, intelligence-boundaries, security, tests, errors, comments, logging,
docs, and simplify fire on every review; types fires when types are added or
modified; doc-first paradigm and bug-fix fire only on their conditions (ad-hoc
commit series with no prepare artifacts / `kind == "bug"`).

### Lane execution gate

Verify every lane whose trigger condition is met ("Always" or conditional match)
was executed. Each executed lane must produce a section in `review-findings.md` —
even if no issues were found. A lane section that says "No findings" proves the
lane ran. A missing lane section means the review is incomplete — stop and execute
the missing lane before writing the verdict.

### 4. Lane detail reference

The full definition of every lane — focus, severity guidance, and the DoD gate or
requirement contract each answers to — lives in the review-lanes catalog
(`software-development/policy/definition-of-done-lanes`, a Required read). Execute
the applicable lanes from that catalog; the severity schema, citation rules, and
verdict arithmetic below govern how their findings resolve to a verdict.

### 5. Quality gates

#### Zero-finding justification

If a review produces 0 Important or higher findings across all lanes, include a "Why No Issues" section in `review-findings.md`:

1. Evidence of paradigm-fit verification (which patterns were checked).
2. Evidence that PRD success criteria were met (which criteria were validated and how).
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

<!-- planned:gate-prepare-artifact-writes -->

Auto-remediation never edits a prepare artifact (`input`, `prd`, `architecture`,
`diagnosis`, `implementation-plan`). A `review-findings` fix targets code. When a
finding reveals the intent or plan itself is wrong, it is not a fix here — it
bounces the todo to prepare, where the prepare orchestrator owns the edit. The
workflow service refuses any prepare-artifact write from a work-phase session, so
this is enforced, not advisory.

<!-- /planned:gate-prepare-artifact-writes -->

**Missing test coverage is never auto-remediated.** For new functionality, test
specs are expected to have been delivered upfront — a gap means the spec or build
phase fell short, not something the reviewer patches. For existing code, coverage
is characterization work that requires the builder's implementation context
(OBSERVE-ASSERT-VERIFY cycle). In both cases, report the finding and request
changes.

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
