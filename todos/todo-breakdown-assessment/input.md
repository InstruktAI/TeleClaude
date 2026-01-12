# Todo Breakdown Assessment

## Problem

Large todos result in complex requirements.md and implementation-plan.md files that are too big for a single AI session to complete. Currently, next-prepare just checks if files exist and marks as ready - no complexity assessment happens.

## Desired Behavior

1. When input.md exists in a todo folder, next-prepare should first assess whether the todo needs to be broken down into smaller todos
2. The assessment uses Definition of Ready criteria (AI-centric):
   - Can this be completed in a single AI session?
   - Is the scope verifiable?
   - Can it be delivered atomically?
   - Is there too much uncertainty?
3. If breakdown needed:
   - Create child todo folders (e.g., `{slug}-1`, `{slug}-2`) each with their own input.md
   - Set dependencies so children execute before parent
   - Update roadmap.md with children in correct order
   - Create breakdown.md as reasoning artifact
   - Update state.json with breakdown status
4. If no breakdown needed:
   - Proceed to requirements.md creation as normal
   - Create breakdown.md explaining why no split

## Key Design Decisions

- Breakdown happens FIRST, before requirements.md or implementation-plan.md
- Child todos start fresh with just input.md, go through same flow
- Parent todo with input.md becomes container (no requirements.md/implementation-plan.md if split)
- Dependencies stored in todos/dependencies.json (existing mechanism)
- state.json gets new `breakdown` property: `{ "assessed": true, "todos": ["slug-1", "slug-2"] }`
- breakdown.md is OUTPUT (reasoning artifact), not INPUT

## Files to Change

1. `teleclaude/core/next_machine.py` - Add breakdown assessment step to `next_prepare()`
2. `~/.agents/commands/next-prepare.md` - Add breakdown assessment instructions for AI
3. `~/.agents/commands/prime-orchestrator.md` - Update to reflect input.md → breakdown flow

## Flow After Implementation

```
input.md exists, no breakdown in state.json
→ AI assesses Definition of Ready
→ IF needs breakdown:
   - Creates child todos with input.md each
   - Sets dependencies
   - Updates roadmap
   - Creates breakdown.md
   - Updates state.json: { breakdown: { assessed: true, todos: [...] } }
   - Parent is done (container)
→ IF no breakdown:
   - Updates state.json: { breakdown: { assessed: true, todos: [] } }
   - Creates breakdown.md (reasoning)
   - Proceeds to requirements.md creation
```

## What This Does NOT Do

- No changes to next-work state machine
- No subtask concept within a single todo
- No tracking beyond the existing dependency mechanism
