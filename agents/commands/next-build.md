---
argument-hint: "[slug]"
description: Worker command - execute implementation plan, commit per task, verify at completion
---

# Build

@~/.teleclaude/docs/software-development/roles/builder.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/build.md

Slug given: "$ARGUMENTS"

---

## Pre-Completion Checklist

Before reporting completion, verify:

1. All tasks in Groups 1-4 are `[x]` in `implementation-plan.md`
2. Tests pass: `make test`
3. Lint passes: `make lint`
4. Working tree is clean: `git status`
   - If not clean, commit: `git add . && git commit -m "build({slug}): final checkpoint"`
5. Verify commits exist: `git log --oneline -10`

## Report Completion

```
BUILD COMPLETE: {slug}

Tasks completed: {count}
Commits made: {count}
Tests: PASSING
Lint: PASSING

Ready for review.
```
