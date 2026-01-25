---
argument-hint: "[slug]"
description: Architect command - analyze codebase and discuss requirements with user
---

# Prepare

@~/.teleclaude/docs/software-development/roles/architect.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/prepare.md

Slug given: "$ARGUMENTS"

---

If no slug: discuss roadmap priorities with the user.

If slug given: create `requirements.md` and `implementation-plan.md` following readiness criteria.

## Report Completion

With slug:

```
PREPARED: {slug}

Requirements: todos/{slug}/requirements.md [COMPLETE]
Implementation Plan: todos/{slug}/implementation-plan.md [COMPLETE]

Ready for build phase.
```

Without slug:

```
ANALYSIS: Roadmap

[Current items and recommendations]

What should we prioritize?
```
