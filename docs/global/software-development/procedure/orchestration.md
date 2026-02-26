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

### Dispatch Rules

- **Reviewers must always be dispatched with `thinking_mode="slow"`.** Review is the last line of defense before merge. A reviewer at `med` or `fast` produces shallow analysis. This is non-negotiable.

### Review Quality Gate (Orchestrator-Owned)

Before accepting a review verdict, the orchestrator must verify the findings document is substantive:

1. Open `review-findings.md` and check that it contains at least one substantive analysis (not just positive observations).
2. For deliveries with 3+ tasks: if the review produces 0 Important+ findings, verify that a "Why no issues" justification section is present with specific evidence.
3. If either check fails, reject the review and re-dispatch with `thinking_mode="slow"`.

This is a document-quality check, not a code review. The orchestrator does not review code — it verifies the reviewer did.

### Orchestration Loop

1. Invoke the work state machine with an optional slug.
2. Receive instruction block.
3. Follow instructions verbatim:
   - Dispatch worker (`telec sessions run`)
   - Start background timer (sleep 300)
   - Stop and wait
4. When notification arrives OR timer expires:
   - Follow POST_COMPLETION steps
   - Invoke the work state machine again
5. Repeat until exit condition.

### Container Slug Handling

- If `telec todo prepare <slug>` returns `CONTAINER:` or `todos/{slug}/state.yaml` has non-empty `breakdown.todos`, treat that slug as a grouping container only.
- Run each child slug via `telec todo work <child>` in dependency order until children complete, and do not dispatch build/review/fix/finalize directly for the container slug.

### When Notification Arrives

1. **Check for user intervention first.** If the user has sent messages, spoken to the worker directly, or changed direction since the worker was dispatched, pause and confirm with the user before proceeding. The notification's implicit instruction ("continue the loop") may be stale.
2. Verify output matches intended outcome.
3. Execute POST_COMPLETION steps (orchestrator responsibility):
   - Mark phase status using `telec todo mark-phase ... --cwd <project-root>` if applicable
   - **Terminate worker session: `telec sessions end <session_id> --computer <computer>`** ← ORCHESTRATOR OWNS THIS
   - Execute any phase-specific cleanup from the state machine instruction
4. **Suppress no-op chatter.** Do not send no-op follow-up messages (`No new input`, `No further input`, `Remain idle`, `Continue standing by`).
5. Send `telec sessions send` only when actionable:
   - gate failure details to fix,
   - explicit answer to a worker question,
   - or a user-directed plan change.
6. If none apply, invoke the state machine again instead of messaging the worker.
7. Invoke the work state machine to continue.

### When Timer Expires

1. **Check for user intervention first.** If the user has sent messages, spoken to the worker directly, or changed direction since the timer was set, the timer's intent is stale — discard the encoded instructions and re-evaluate from the current state. Do not blindly resume the orchestration loop.
2. Check session output using the session inspection tool.
3. Determine status and take action.
4. If worker still running, reset timer and continue waiting.

### When Worker Needs Help

1. Cancel old timer.
2. Send guidance pointing to docs, not implementation details. Do not attempt to resolve issues by modifying code or tests yourself; always provide guidance via message instead.
3. Start new timer and continue waiting.
4. Do not send acknowledgement-only/no-op guidance.

### Agent Degradation Handling (Orchestrator-Owned)

1. If dispatch fails due to quota/rate-limit/provider instability, mark provider status immediately.
2. Use `telec agents status <agent> --status <status> --reason <reason> [--until <iso8601>]`:
   - `status="degraded"` when the agent should be excluded from automatic fallback selection.
   - `status="unavailable"` for time-bounded outages/rate limits.
   - Use `--clear` when recovered.
3. Re-run `telec todo work ...` after status update.
4. Do not delegate this decision to workers; only orchestrator should mutate provider status.

### Review Round Limit Handling (Orchestrator-Owned)

When `telec todo work ...` returns `REVIEW_ROUND_LIMIT`, the orchestrator must close the loop pragmatically instead of punting by default.

1. Inspect current evidence before deciding:
   - `todos/{slug}/review-findings.md`
   - `todos/{slug}/state.yaml`
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
