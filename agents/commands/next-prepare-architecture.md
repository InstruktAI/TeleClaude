---
argument-hint: '[slug]'
description: Worker command - derive and write the code-grounded architecture artifact
---

# Prepare Architecture

You are now the Architect for prepare architecture.

## Required reads

- @~/.teleclaude/docs/general/principle/stewardship.md
- @~/.teleclaude/docs/general/principle/calibration.md
- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/software-development/principle/design-fundamentals.md
- @~/.teleclaude/docs/software-development/principle/intelligence-boundaries.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/architecture.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discipline.md
- @docs/_snippets/slug-resolution.md

## Purpose

Ground the approved PRD in the codebase and author the architectural design
DIRECTLY into the affected doc snippets (domain spec at
`docs/project/spec/domain/<context>.md` and/or cross-cutting design docs at
`docs/project/design/architecture-v2/*.md`), then write a thin `architecture`
artifact that indexes which snippets were touched and why so downstream
implementation planning can rely on it.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} prd`
- Existing `architecture-review-findings` when present
- Relevant code paths discovered from the PRD and codebase
- The domain spec / design-doc snippets the PRD's "Docs to author or update"
  section names

## Outputs

- Architectural design authored directly into the affected domain spec /
  architecture-v2 design-doc snippets, each with frontmatter `status: target`
  and `delivered_by: [<slug>]`
- A thin `architecture` artifact via
  `telec todo artifacts write {slug} architecture <content>` that is ONLY an
  index/log of which snippets were touched and why — NOT the design body
- Optional `telec todo stamp {slug} --architecture-skipped <reason>` for
  trivial work that earns no design change

## Steps

Follow the architecture procedure.

## Discipline

Follow the architecture procedure's discipline.
