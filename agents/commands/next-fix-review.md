---
argument-hint: "[slug]"
description: Worker command - fix issues identified in code review findings
---

# Fix Review Issues

@~/.teleclaude/docs/software-development/roles/builder.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/fix-review.md

Slug given: "$ARGUMENTS"

---

## Your Role

You are a **Worker** executing the Fix phase. You address issues identified in the code review.

## Your Scope

1. Read `todos/{slug}/review-findings.md` to understand what needs fixing
2. Address each finding, prioritizing by severity (CRITICAL > HIGH > MEDIUM > LOW)
3. Make minimal, focused changes - don't refactor beyond what's needed
4. Run tests and lint to verify fixes
5. Commit fixes with clear messages referencing the finding
6. **STOP** when all findings are addressed

## FORBIDDEN Actions

**You are a worker, not an orchestrator. The following are STRICTLY FORBIDDEN:**

- ❌ **DO NOT** call `teleclaude__next_work` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__next_prepare` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__mark_phase` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__start_session` - you cannot spawn other workers
- ❌ **DO NOT** call `teleclaude__send_message` to other sessions
- ❌ **DO NOT** call `teleclaude__run_agent_command` - you cannot dispatch commands
- ❌ **DO NOT** modify `state.json` directly
- ❌ **DO NOT** merge branches or finalize work
- ❌ **DO NOT** add new features beyond the findings

## When You Are Done

1. Ensure all tests pass
2. Ensure lint passes
3. Report completion:

```
FIX COMPLETE: {slug}

Findings addressed: {count}
Commits made: {count}
Tests: PASSING
Lint: PASSING

Ready for re-review.
```

4. **STOP.** Do not invoke any further tools. The orchestrator will handle the next phase.

**Remember: Your job is to FIX the findings, then STOP. The orchestrator handles everything else.**
