---
description: 'Prepare phase entry point. Decide roadmap focus, assess input readiness, and review requirements/plan.'
id: 'software-development/procedure/lifecycle/prepare'
scope: 'domain'
type: 'procedure'
---

# Prepare — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/input-assessment.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/requirements-analysis.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/implementation-planning.md

## Goal

1. Read `todos/roadmap.md`.
2. **Bugs Sentinel:** Read `todos/bugs.md` and identify any blockers or relevant bugs that must be addressed before this item is ready.
3. Report current items and recommendations:
   - What items are pending?
   - What should be prioritized and why?
   - Any items that need clarification?
4. Discuss with the orchestrator until a slug is chosen.

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

**Bugs Check:**
- [ ] Any blockers or relevant bugs found in `todos/bugs.md` have been addressed or accounted for.

What are your thoughts?
```

Return:

```
PREPARED: {slug}
Ready for implementation.
```

## Preconditions

- `todos/roadmap.md` and `todos/bugs.md` exist and are readable.
- Target slug folder exists or can be created.

## Steps

1. Review roadmap and identify candidate slugs.
2. **Scan Bugs:** Check `todos/bugs.md`. If blockers exist, prioritize fixing them via the **Bugs Self-Healing** route before preparing new features.
3. Run input assessment and requirements analysis for the chosen slug.
4. Review or draft the implementation plan.
5. Confirm readiness with the orchestrator and return `PREPARED`.

## Outputs

- Preparation report and selected slug marked ready for implementation.

## Recovery

- If no ready items, return `NO_READY_ITEMS` and recommend next preparation tasks.
