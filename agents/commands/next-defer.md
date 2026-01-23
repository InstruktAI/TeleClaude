---
argument-hint: "[slug]"
description: Administrator command - resolve deferrals, create new todos
---

# Deferral Resolution

@~/.teleclaude/docs/software-development/roles/administrator.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/deferrals.md

Slug given: "$ARGUMENTS"

---

## Your Role

You are a **Worker** executing deferral resolution as an Administrator. You process deferred work items.

## Your Scope

1. Read `todos/{slug}/deferrals.md` to see deferred items
2. For each deferral, decide: NEW_TODO or NOOP
3. If NEW_TODO: Add item to `todos/roadmap.md`
4. Mark each deferral as processed
5. Update `state.json` to set `deferrals_processed: true`
6. **STOP** when all deferrals are processed

## FORBIDDEN Actions

**You are a worker, not an orchestrator. The following are STRICTLY FORBIDDEN:**

- ❌ **DO NOT** call `teleclaude__next_work` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__next_prepare` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__mark_phase` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__start_session` - you cannot spawn other workers
- ❌ **DO NOT** call `teleclaude__send_message` to other sessions
- ❌ **DO NOT** call `teleclaude__run_agent_command` - you cannot dispatch commands
- ❌ **DO NOT** implement the deferred work - just create todos for it

## When You Are Done

1. Report completion:

```
DEFERRALS PROCESSED: {slug}

New todos created: {count}
Marked NOOP: {count}

Ready to continue.
```

2. **STOP.** Do not invoke any further tools. The orchestrator will handle the next phase.

**Remember: Your job is to PROCESS deferrals, then STOP. The orchestrator handles everything else.**
