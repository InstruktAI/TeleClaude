---
description: 'Prepare test-specs procedure. Produces a language-agnostic prose test-specs artifact from human-approved PRD and optional reviewer-approved architecture; build phase later translates it into executable tests.'
domain: 'software-development'
id: 'software-development/procedure/lifecycle/prepare/prepare-specs'
scope: 'domain'
type: 'procedure'
visibility: 'public'
---

# Prepare Specs — Procedure

> **DEPRECATED — merged into intake.**
>
> Per `software-development/principle/documentation-first-development`
> Implication #9, there is no separate test-specs phase. Gherkin acceptance
> scenarios live in the feature spec snippet and are authored during the
> intake phase, alongside the business value framing. The hub-and-spoke
> model removes the structural reason this phase existed — there is no
> separate `test-specs` workflow.artifact to produce.
>
> The state machine no longer transitions through a test-specs phase.
> Orchestrators MUST NOT dispatch a `next-prepare-specs` worker. If a
> feature spec's Gherkin needs refinement after intake (because
> architecture-phase domain spec updates surfaced new scenarios), the
> architecture worker appends to the feature spec snippet in the same
> phase — no separate cycle needed.
>
> This file is retained for historical reference only and will be removed
> in a future cleanup.

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/test-structure.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

DEPRECATED — see banner above. The original test-specs phase derived a
Gherkin (`Given / When / Then`) behavioral contract from the PRD into a
separate `test-specs` workflow.artifact. In the doc-first model, Gherkin
is authored DIRECTLY into the feature spec snippet during intake; no
separate phase exists.

### Output target (deprecated)

This phase has no output target. The Gherkin behavioral contract lives in
the **feature spec snippet** at
`docs/project/spec/feature/<context>/<concept-name>.md` — authored during
intake. Architecture phase may append to it. No phase dedicated to
Gherkin production exists.

### Outcome

Confirm the feature spec snippet(s) for this slug contain complete Gherkin
scenarios covering every PRD success criterion + every architectural change
worth a behavioral assertion. Refine where gaps exist. The feature spec is
the binding behavioral contract a build worker reads and an executable test
suite later mirrors. Test-specs phase is a CHECKPOINT on Gherkin
completeness, not a re-author.

## Preconditions

- `prd` exists and has been approved by the real human.
- `architecture` exists and has reviewer approval, or `architecture_skipped` is stamped.
- Slug is active and not delivered.

## Steps

1. Read `telec todo artifacts read {slug} prd` in full.
2. Read `telec todo artifacts read {slug} architecture` when present; otherwise read the architecture skip reason from state.
3. For each PRD success criterion (outcome-shaped, in PO language), derive at least one `Given / When / Then` scenario that makes the outcome verifiable. The PRD says *what* counts as success; test-specs says *how to test* it.
4. Add Gherkin scenarios for architecture-derived quality implications where applicable: audit logging, performance budgets, observability, accessibility, security boundaries, config behavior, and compatibility promises. These are testable concerns the PRD doesn't carry.
5. Keep every entry language-agnostic. Name likely behavioral surfaces when helpful, but do not name concrete test files unless the architecture already makes that surface explicit.
6. Write the artifact:

```bash
telec todo artifacts write {slug} test-specs <content>
```

7. **Final step — advance.** When the test-specs artifact is written, call:

```bash
telec todo prepare {slug}
```

The state machine routes the next action. It will direct you to dispatch the
test-specs reviewer and tail it. On `approve` it advances to the plan phase.
On `needs_work` it routes you back here to address the findings; read
`telec todo artifacts read {slug} spec-review-findings`, update the
test-specs artifact to resolve each finding, then advance again.

## Outputs

- `test-specs` artifact stored in the todo DB.
- Reviewer verdict `approve` on `test_spec_review` is the authority that advances this phase.

## Recovery

- Sparse PRD: return to intake with a concrete finding instead of inventing criteria.
- Architecture gap: mark the affected spec entry with the missing architecture question and request architecture revision.
- Spec-during-build ambiguity: add a `Notes` line to the spec entry describing what the builder must verify before choosing the concrete test shape.
