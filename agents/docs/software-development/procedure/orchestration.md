---
description:
  Orchestration loop for the next-work state machine and worker session
  handling.
id: software-development/procedure/orchestration
scope: domain
type: procedure
---

# Orchestration Procedure

## Required reads

- @software-development/procedure/lifecycle-overview

## Requirements

@~/.teleclaude/docs/software-development/procedure/lifecycle-overview.md

## Preparation Flow

Discussion results go in `todos/{slug}/input.md`. Use the preparation state machine to assess and structure.

## The Orchestration Loop

1. Invoke the work state machine with an optional slug.
2. Receive instruction block.
3. Follow instructions verbatim:
   - Dispatch worker (run_agent_command)
   - Start background timer (sleep 300)
   - Stop and wait
4. When notification arrives OR timer expires:
   - Follow POST_COMPLETION steps
   - Invoke the work state machine again
5. Repeat until exit condition.

## Handling Worker Sessions

### When Notification Arrives

1. Verify output matches intended outcome.
2. Execute POST_COMPLETION steps (orchestrator responsibility):
   - Mark phase status using `teleclaude__mark_phase()` if applicable
   - **Terminate worker session: `teleclaude__end_session(computer, session_id)`** ← ORCHESTRATOR OWNS THIS
   - Execute any phase-specific cleanup from the state machine instruction
3. Invoke the work state machine to continue.

### When Timer Expires

1. Check session output using the session inspection tool.
2. Determine status and take action.
3. If worker still running, reset timer and continue waiting.

### When Worker Needs Help

1. Cancel old timer.
2. Send guidance pointing to docs, not implementation details.
3. Start new timer and continue waiting.

## Guidance Principle

- Point workers to `todos/{slug}/requirements.md` or `implementation-plan.md`.
- Reference project docs or standards.
- Never dictate specific commands or code.

## Exit Conditions

The loop terminates when the work state machine returns:

- `NO_READY_ITEMS` (run the preparation state machine first)
- `COMPLETE`
- Error requiring human intervention
