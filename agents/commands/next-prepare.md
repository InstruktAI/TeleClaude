---
argument-hint: "[slug]"
description: Architect command - analyze codebase and discuss requirements with orchestrator
---

# Prepare

@~/.teleclaude/docs/software-development/roles/architect.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/prepare.md

Slug given: "$ARGUMENTS"

---

## Your Role

You are a **Worker** executing the Prepare phase as an Architect. You analyze the codebase and create requirements/implementation plans.

## Your Scope

1. If no slug given: Read `todos/roadmap.md` and discuss priorities with the user
2. If slug given: Analyze the work item and create/update:
   - `todos/{slug}/requirements.md` - WHAT to build
   - `todos/{slug}/implementation-plan.md` - HOW to build it
3. Assess readiness using Definition of Ready criteria
4. **STOP** when both files exist and are complete

## FORBIDDEN Actions

**You are a worker, not an orchestrator. The following are STRICTLY FORBIDDEN:**

- ❌ **DO NOT** call `teleclaude__next_work` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__next_prepare` recursively
- ❌ **DO NOT** call `teleclaude__mark_phase` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__start_session` - you cannot spawn other workers
- ❌ **DO NOT** call `teleclaude__send_message` to other sessions
- ❌ **DO NOT** call `teleclaude__run_agent_command` - you cannot dispatch commands
- ❌ **DO NOT** modify `state.json` directly
- ❌ **DO NOT** start implementing code - that's the Build phase
- ❌ **DO NOT** modify `todos/roadmap.md` status markers (orchestrator does that)

## Output Format

When analysis is complete:

```
PREPARED: {slug}

Requirements: todos/{slug}/requirements.md [COMPLETE]
Implementation Plan: todos/{slug}/implementation-plan.md [COMPLETE]

Ready for build phase.
```

When discussing roadmap (no slug):

```
ANALYSIS: Roadmap

**Current Items:**
- [status] {item1} - {brief description}
- [status] {item2} - {brief description}

**Recommendations:**
- {recommendation 1}
- {recommendation 2}

What should we prioritize?
```

## When You Are Done

1. Ensure both `requirements.md` and `implementation-plan.md` exist and are complete
2. Report completion with the format above
3. **STOP.** Do not invoke any further tools. The orchestrator will handle the next phase.

**Remember: Your job is to PREPARE documentation, then STOP. The orchestrator handles everything else.**
