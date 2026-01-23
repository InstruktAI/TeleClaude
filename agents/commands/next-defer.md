---
argument-hint: "[slug]"
description: Administrator command - resolve deferrals, create new todos
---

# Deferral Resolution

@~/.teleclaude/docs/software-development/roles/administrator.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/deferrals.md

Slug given: "$ARGUMENTS"

---

Read `todos/{slug}/deferrals.md`. For each deferral: decide NEW_TODO or NOOP. Create new todos in roadmap if needed. Mark deferrals as processed.

## Report Completion

```
DEFERRALS PROCESSED: {slug}

New todos created: {count}
Marked NOOP: {count}

Ready to continue.
```

**STOP.** Do not invoke any further tools.
