---
argument-hint: "[slug]"
description: Administrator command - resolve deferrals, create new todos
---

# Deferral Resolution

@~/.teleclaude/docs/software-development/roles/administrator.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/deferrals.md

Slug given: "$ARGUMENTS"

---

## Steps

1. Read `todos/{slug}/deferrals.md`.
2. For each deferral: decide NEW_TODO or NOOP.
3. Create new todos in roadmap if needed.
4. Mark deferrals as processed.

## Report Completion

```
DEFERRALS PROCESSED: {slug}

New todos created: {count}
Marked NOOP: {count}

Ready to continue.
```
