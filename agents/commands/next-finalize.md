---
argument-hint: "[slug]"
description: Worker command - merge, log delivery, cleanup after review passes
---

# Finalize

@~/.teleclaude/docs/software-development/roles/finalizer.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/finalize.md

Slug given: "$ARGUMENTS"

---

Verify review is APPROVED. Merge worktree branch to main. Log delivery. Clean up.

## Report Completion

```
FINALIZE COMPLETE: {slug}

Branch merged: {branch_name}
Delivery logged: YES
Cleanup: COMPLETE

Work item delivered.
```

**STOP.** Do not invoke any further tools.
