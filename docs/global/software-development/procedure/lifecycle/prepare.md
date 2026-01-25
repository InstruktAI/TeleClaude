---
description:
  Prepare phase entry point. Decide roadmap focus, assess input readiness,
  and review requirements/plan.
id: software-development/procedure/lifecycle/prepare
scope: domain
type: procedure
---

# Prepare — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/input-assessment
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/requirements-analysis
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/implementation-planning

## Goal

1. Read `todos/roadmap.md`.
2. Report current items and recommendations:
   - What items are pending?
   - What should be prioritized and why?
   - Any items that need clarification?
3. Discuss with the orchestrator until a slug is chosen.

```
ANALYSIS: {slug}

**Context:** [What I found in the codebase]

**Findings:**
- [Finding 1]
- [Finding 2]

**Recommendations:**
- [Recommendation 1]
- [Recommendation 2]

**Open Questions:**
- [Question 1]
- [Question 2]

What are your thoughts?
```

Return:

```
PREPARED: {slug}
Ready for implementation.
```

## Preconditions

- `todos/roadmap.md` exists and is readable.
- Target slug folder exists or can be created.

## Steps

1. Review roadmap and identify candidate slugs.
2. Run input assessment and requirements analysis for the chosen slug.
3. Review or draft the implementation plan.
4. Confirm readiness with the orchestrator and return `PREPARED`.

## Outputs

- Preparation report and selected slug marked ready for implementation.

## Recovery

- If no ready items, return `NO_READY_ITEMS` and recommend next preparation tasks.
