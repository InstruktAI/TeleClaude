---
description: 'Orchestration loop for the next-work state machine and worker session handling.'
id: 'software-development/procedure/orchestration'
scope: 'domain'
type: 'procedure'
---

# Orchestration — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle-overview.md

## Goal

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
2. Send guidance pointing to docs, not implementation details. Do not attempt to resolve issues by modifying code or tests yourself; always provide guidance via message instead.
3. Start new timer and continue waiting.

### Agent Degradation Handling (Orchestrator-Owned)

1. If dispatch fails due to quota/rate-limit/provider instability, mark provider status immediately.
2. Use `teleclaude__mark_agent_status(agent, status, reason, unavailable_until?)`:
   - `status="degraded"` when the agent should be excluded from automatic fallback selection.
   - `status="unavailable"` for time-bounded outages/rate limits.
   - `status="available"` when recovered.
3. Re-run `teleclaude__next_work(...)` after status update.
4. Do not delegate this decision to workers; only orchestrator should mutate provider status.

### Review Round Limit Handling (Orchestrator-Owned)

When `teleclaude__next_work(...)` returns `REVIEW_ROUND_LIMIT`, the orchestrator must close the loop pragmatically instead of punting by default.

1. Inspect current evidence before deciding:
   - `todos/{slug}/review-findings.md`
   - `todos/{slug}/state.json`
   - Fix commits since `review_baseline_commit`
2. Decide and act:
   - If unresolved **Critical** findings remain, keep `review=changes_requested`, record an explicit blocker summary, and escalate with a concrete decision request.
   - If only non-critical findings remain and the implementation is stable, mark `review=approved`, capture residual work as follow-up/deferred items, and continue lifecycle progression.
3. Always end the active worker session before applying this decision.
4. Record rationale in todo artifacts so the closure is auditable.

- Point workers to `todos/{slug}/requirements.md` or `implementation-plan.md`.
- Reference project docs or standards.
- Never dictate specific commands or code.

The loop terminates when the work state machine returns:

- `NO_READY_ITEMS` (run the preparation state machine first)
- `COMPLETE`
- Non-recoverable error requiring intervention

## Preconditions

- Work item state machine is available and in a known phase.
- Worker session is running or ready to be dispatched.

## Steps

1. Dispatch the worker with the appropriate state machine command.
2. Start a timer and wait for completion.
3. On timer expiry, inspect session output and decide next action.
4. Provide guidance using docs when workers are blocked.

## Outputs

- Work item progresses through phases with documented status.

## Recovery

- If the worker stalls, request a summary and restart with clearer instructions.
