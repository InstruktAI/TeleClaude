---
id: 'software-development/procedure/lifecycle/prepare/prepare-specs'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Prepare test-specs procedure. Produces a language-agnostic prose test-specs artifact from human-approved PRD and optional reviewer-approved architecture; build phase later translates it into executable tests.'
---

# Prepare Specs — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/test-structure.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

Produce a prose `test-specs` artifact that covers the PRD success criteria and
architecture quality implications without writing source code. The artifact is
the behavioral contract a build worker later translates into project-specific
tests.

## Preconditions

- `prd` exists and has been approved by the real human.
- `architecture` exists and has reviewer approval, or `architecture_skipped` is stamped.
- Slug is active and not delivered.

## Steps

1. Read `telec todo artifacts read {slug} prd` in full.
2. Read `telec todo artifacts read {slug} architecture` when present; otherwise read the architecture skip reason from state.
3. For each PRD success criterion, write at least one Given/When/Then prose spec.
4. Add quality implications from architecture where applicable: audit logging, performance budgets, observability, accessibility, security boundaries, config behavior, and compatibility promises.
5. Keep every entry language-agnostic. Name likely behavioral surfaces when helpful, but do not name concrete test files unless the architecture already makes that surface explicit.
6. Write the artifact:

```bash
telec todo artifacts write {slug} test-specs <content>
```

## Outputs

- `test-specs` artifact stored in the todo DB.
- Reviewer verdict `approve` on `test_spec_review` is the authority that advances this phase.

## Recovery

- Sparse PRD: return to intake with a concrete finding instead of inventing criteria.
- Architecture gap: mark the affected spec entry with the missing architecture question and request architecture revision.
- Spec-during-build ambiguity: add a `Notes` line to the spec entry describing what the builder must verify before choosing the concrete test shape.
