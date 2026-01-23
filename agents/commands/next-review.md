---
argument-hint: "[slug]"
description: Worker command - review code against requirements, output findings with verdict
---

# Review

@~/.teleclaude/docs/software-development/roles/reviewer.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/review.md

Slug given: "$ARGUMENTS"

---

## Your Task

Review code changes in the worktree against requirements and architecture.

Write findings to `todos/{slug}/review-findings.md` with verdict: APPROVE or REQUEST CHANGES.

## Report Completion

```
REVIEW COMPLETE: {slug}

Verdict: [APPROVE | REQUEST CHANGES]
Findings: {count}
```

**STOP.** Do not invoke any further tools.
