---
description: 'Prepare test-specs procedure. Produces a language-agnostic prose test-specs artifact from human-approved PRD and optional reviewer-approved architecture; build phase later translates it into executable tests.'
domain: 'software-development'
id: 'software-development/procedure/lifecycle/prepare/prepare-specs'
scope: 'domain'
type: 'procedure'
visibility: 'public'
---

# Prepare Specs — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/test-structure.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

Your focus this turn is the test-specs phase: derive a Gherkin
(`Given / When / Then`) behavioral contract from the PRD's outcome-shaped
success criteria and the architecture's testable quality implications. The
wider prepare lifecycle is still yours; this phase is one focused part of it.

### Outcome

Derive a `test-specs` artifact — a Gherkin (`Given / When / Then`) behavioral
contract — from the PRD's outcome-shaped success criteria and the architecture's
testable quality implications. The artifact is the behavioral contract a build
worker later translates into project-specific tests. Test-specs is the **only**
phase that produces Gherkin in the prepare lifecycle; the PRD carries outcomes
in PO language, not `Given / When / Then`.

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
