---
id: 'software-development/procedure/lifecycle/prepare/review-architecture'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Architecture review phase. Validate the architecture artifact against the approved PRD, project architecture, codebase reality, and platform defaults.'
---

# Review Architecture — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/software-development/principle/design-fundamentals.md
- @~/.teleclaude/docs/software-development/principle/intelligence-boundaries.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

Validate the `architecture` artifact against the approved PRD, project
architecture docs, codebase reality, and platform defaults. The artifact must
ground every claim it makes and align with existing scaffolds and flavors
rather than inventing one-off patterns.

## Preconditions

- `telec todo artifacts read {slug} prd` exists and is approved.
- `telec todo artifacts read {slug} architecture` exists.
- Slug is active and not delivered.

## Steps

### 1. Read context

- `telec todo artifacts read {slug} prd` — the approved product contract.
- `telec todo artifacts read {slug} architecture` — the artifact under review.
- Relevant code paths and project architecture docs cited by the artifact.
- Apply the domain-context loading rule from the preparation artifact quality
  policy before validating.

### 2. Verify grounding

Verify cited code paths, events, services, scaffold choices, and state
ownership against source. Architectural claims that are not grounded in
existing code or documented patterns are defective.

### 3. Reject undocumented divergence from defaults

Per `architectural-defaults`: reject claims that diverge from the
architectural defaults without explicit rationale. Divergence requires named
trade-offs that justify the alternative.

### 4. Write findings only when unresolved issues remain

When findings exist, write them via:

```bash
telec todo artifacts write {slug} architecture-review-findings <content>
```

Findings carry the severity schema and policy citation requirement defined
in `lifecycle/work/review` §6.

### 5. Write verdict

Stamp the review verdict:

```bash
telec todo stamp {slug} --verdict approve --phase architecture_review
# or
telec todo stamp {slug} --verdict needs_work --phase architecture_review
```

## Outputs

- Verdict stamped with `telec todo stamp`.
- `telec todo artifacts read {slug} architecture-review-findings` when findings
  exist.

## Discipline

Review the architecture, not the implementation. Do not add scope, do not
write the implementation plan, and do not silently repair architectural
decisions that need the drafter or human to own them.

- Every finding must cite the specific policy, DoD line, principle, or
  spec it violates. A finding without a citation is not a finding — drop it.
- The schema mirrors the plan-review and specs-review forbidden-moves block:
  no fourth tier (no "Suggestion", "nit", "polish", "non-blocking",
  "follow-up"); no pre-existing-pattern dodge; no uncited findings; no
  severity-softening to reach approve.

## Recovery

- If the architecture is materially correct but PRD is ambiguous, flag a
  blocker — the PRD must be re-engaged before the architecture can advance.
- If the architecture diverges from the defaults with an unstated rationale,
  mark `needs_work` rather than guessing the rationale.

## See Also

- ~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- ~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/architecture.md
