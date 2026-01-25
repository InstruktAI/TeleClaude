---
argument-hint: "[slug]"
description: Worker command - fix issues identified in code review findings
---

# Fix Review Issues

@~/.teleclaude/docs/software-development/roles/builder.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/fix-review.md

Slug given: "$ARGUMENTS"

---

Address findings in `todos/{slug}/review-findings.md`. Prioritize by severity. Commit per fix.

Verify tests and lint pass before reporting completion.

## Report Completion

```
FIX COMPLETE: {slug}

Findings addressed: {count}
Commits made: {count}
Tests: PASSING
Lint: PASSING

Ready for re-review.
```
