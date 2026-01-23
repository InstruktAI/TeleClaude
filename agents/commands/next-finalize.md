---
argument-hint: "[slug]"
description: Worker command - merge, log delivery, cleanup after review passes
---

# Finalize

@~/.teleclaude/docs/software-development/roles/finalizer.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/finalize.md

Slug given: "$ARGUMENTS"

---

## Your Role

You are a **Worker** executing the Finalize phase. You merge approved work and clean up.

## Your Scope

1. Verify review status is APPROVED in `todos/{slug}/state.json`
2. Merge the worktree branch to main
3. Log delivery in `todos/delivered.md`
4. Clean up the todo folder and worktree
5. **STOP**

## FORBIDDEN Actions

**You are a worker, not an orchestrator. The following are STRICTLY FORBIDDEN:**

- ❌ **DO NOT** call `teleclaude__next_work` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__next_prepare` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__mark_phase` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__start_session` - you cannot spawn other workers
- ❌ **DO NOT** call `teleclaude__send_message` to other sessions
- ❌ **DO NOT** call `teleclaude__run_agent_command` - you cannot dispatch commands
- ❌ **DO NOT** finalize if review status is not APPROVED
- ❌ **DO NOT** make code changes - finalize only handles merge/cleanup

## When You Are Done

1. Report completion:

```
FINALIZE COMPLETE: {slug}

Branch merged: {branch_name}
Delivery logged: YES
Cleanup: COMPLETE

Work item delivered.
```

2. **STOP.** Do not invoke any further tools. The orchestrator will handle the next item.

**Remember: Your job is to FINALIZE and CLEAN UP, then STOP. The orchestrator handles everything else.**
