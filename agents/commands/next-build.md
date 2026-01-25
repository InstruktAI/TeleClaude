---
argument-hint: "[slug]"
description: Worker command - execute implementation plan, commit per task, verify at completion
---

# Build

@~/.teleclaude/docs/software-development/roles/builder.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/build.md

Slug: "$ARGUMENTS"

---

## Steps

1. Execute the build phase for the slug.
2. Run verification steps required by the build procedure.
3. Summarize results in the completion report.

## Report Completion

```
BUILD COMPLETE: {slug}

Tasks completed: {count}
Commits made: {count}
Tests: PASSING
Lint: PASSING

Ready for review.
```
