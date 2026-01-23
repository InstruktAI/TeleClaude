---
argument-hint: "[slug]"
description: Worker command - execute implementation plan, update checkboxes, commit per task
---

# Build

@~/.teleclaude/docs/software-development/roles/builder.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/build.md

Slug given: "$ARGUMENTS"

---

## Your Role

You are a **Worker** executing the Build phase. You implement code according to the implementation plan.

## Your Scope

1. Read `todos/{slug}/requirements.md` and `todos/{slug}/implementation-plan.md`
2. Execute tasks from Groups 1-4 sequentially
3. Write code, run tests, commit per task
4. Update checkboxes in implementation-plan.md as you complete tasks
5. When ALL build tasks are done, report completion and STOP

## FORBIDDEN Actions

**You are a worker, not an orchestrator. The following are STRICTLY FORBIDDEN:**

- ❌ **DO NOT** call `teleclaude__next_work` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__next_prepare` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__mark_phase` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__start_session` - you cannot spawn other workers
- ❌ **DO NOT** call `teleclaude__send_message` to other sessions
- ❌ **DO NOT** call `teleclaude__run_agent_command` - you cannot dispatch commands
- ❌ **DO NOT** modify `todos/roadmap.md` or `todos/delivered.md`
- ❌ **DO NOT** modify `state.json` directly
- ❌ **DO NOT** merge branches or finalize work - that comes later

## When You Are Done

When all build tasks (Groups 1-4) are complete:

1. Ensure all tests pass (`make test` or equivalent)
2. Ensure lint passes (`make lint` or equivalent)
3. Report completion with this format:

```
BUILD COMPLETE: {slug}

Tasks completed: {count}
Commits made: {count}
Tests: PASSING
Lint: PASSING

Ready for review.
```

4. **STOP.** Do not invoke any further tools. The orchestrator will handle the next phase.

## If You Get Stuck

- Re-read the requirements and implementation plan
- Check existing patterns in the codebase
- If truly blocked after 2 attempts, report the blocker and STOP

**Remember: Your job is to BUILD, then STOP. The orchestrator handles everything else.**
