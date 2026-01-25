---
description:
  Prepare phase entry point. Decide roadmap focus, assess input readiness,
  and review requirements/plan.
id: software-development/procedure/lifecycle/prepare
scope: domain
type: procedure
---

# Lifecycle: Prepare — Procedure

## Required reads

- @software-development/procedure/lifecycle/prepare/input-assessment
- @software-development/procedure/lifecycle/prepare/requirements-analysis
- @software-development/procedure/lifecycle/prepare/implementation-planning

## When No Slug Is Provided

1. Read `todos/roadmap.md`.
2. Report current items and recommendations:
   - What items are pending?
   - What should be prioritized and why?
   - Any items that need clarification?
3. Discuss with the orchestrator until a slug is chosen.

## When Slug Is Provided

@~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/input-assessment.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/requirements-analysis.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/implementation-planning.md

## Output Format

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

## When Both Files Exist

Return:

```
PREPARED: {slug}
Ready for implementation.
```
