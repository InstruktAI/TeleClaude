---
description: 'Orchestration loop for the next-work state machine and worker session handling.'
id: 'general/procedure/orchestration'
scope: 'global'
type: 'procedure'
---

# Orchestration — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/overview.md

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

1. Invoke the state machine (`telec todo work`, `telec todo prepare`, or `telec todo create`) with an optional slug.
2. Receive the instruction block.
3. Execute the instructions verbatim. The state machine output is a linear script — follow it top-to-bottom without branching or decision-making.
4. When a notification arrives OR the heartbeat timer expires, invoke the state machine again.
5. Repeat until the state machine emits a terminal cleanup script that includes `telec sessions end self`.

The state machine owns every concrete decision: dispatch, session ending, phase transitions, fix relay, terminal cleanup. The orchestrator never decides session lifecycle or branches on verdict — if the script says `telec sessions end <id>`, end that session; if the script says `telec sessions send <id> "..."`, send that message. The only orchestrator-owned behaviors are heartbeat management and tailing discipline.

### Container Slug Handling

- If `telec todo prepare <slug>` returns `CONTAINER:` or `todos.db` state has non-empty `breakdown.todos`, treat that slug as a grouping container only.
- Run each child slug via `telec todo work <child>` in dependency order until children complete, and do not dispatch build/review/fix/finalize directly for the container slug.

### Tailing Discipline

The orchestrator maintains a **marker timestamp** per dispatched worker, initialized
to the dispatch time. All session inspection follows this protocol:

- **First tail** (after dispatch): use a full window (`telec sessions tail <session_id> --tools --thinking`) to establish context. Save the timestamp of the last message as the marker.
- **All subsequent tails**: use `--since <marker>` to retrieve only new output. This avoids re-reading content already seen and makes progress detection trivial — if `--since` returns no new messages, nothing happened.
- After every tail, update the marker to the latest message timestamp from the response.
- Each `telec sessions tail` response includes `last_input_at`, `last_activity`, `last_agent_stop_at`, and computed `agent_status`.

Status semantics:

- `active`: `last_activity` exists and the latest observed activity is not the agent stop event.
- `idle`: `last_activity` exists and `last_agent_stop_at == last_activity`.
- `unknown`: no `last_activity` has been recorded yet.

### When Notification Arrives

1. **Check for user intervention first.** If the user has sent messages, spoken to the worker directly, or changed direction since the worker was dispatched, pause and confirm with the user before proceeding. The notification's implicit instruction ("continue the loop") may be stale.
2. Tail the session (first time: full window; subsequent tails: `--since <marker>`).
3. Update the marker to the latest message timestamp when new messages appear.
4. If `agent_status` is `active`, reset the heartbeat timer and continue waiting.
5. If `agent_status` is `idle`, invoke the state machine again (`telec todo work`, `telec todo prepare`, or `telec todo create` depending on the loop). Execute the returned script verbatim — it contains any durable state transitions, session-end commands, or `sessions send` relays for this exact moment.
6. If `agent_status` is `unknown`, continue waiting for the next event.
7. **Suppress no-op chatter.** Do not send no-op follow-up messages (`No new input`, `No further input`, `Remain idle`, `Continue standing by`). Only send `telec sessions send` when the state machine output explicitly instructs it.

### When Timer Expires

1. **Check for user intervention first.** If the user has sent messages, spoken to the worker directly, or changed direction since the timer was set, the timer's intent is stale — discard the encoded instructions and re-evaluate from the current state. Do not blindly resume the orchestration loop.
2. Tail the session (first time: full window; subsequent tails: `--since <marker>`).
3. Update the marker to the latest message timestamp when new messages appear.
4. If `agent_status` is `active`, reset the heartbeat timer and continue waiting.
5. If `agent_status` is `idle`, invoke the state machine again and execute its returned script verbatim.
6. If `agent_status` is `unknown`, continue waiting for the next event.

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
   - `telec todo artifacts read {slug} review-findings`
   - `todos.db` state
   - Fix commits since `review_baseline_commit`
2. Decide and act:
   - If unresolved **Critical** findings remain, keep `review=changes_requested`, record an explicit blocker summary, and escalate with a concrete decision request. Sessions stay alive as signal for the human.
   - If only non-critical findings remain and the implementation is stable, mark `review=approved`, capture residual work as follow-up/deferred items, and continue lifecycle progression. The state machine will emit cleanup commands on the next successful terminal.
3. Record rationale in todo artifacts so the closure is auditable.

- Point workers to `telec todo artifacts read {slug} requirements` or `implementation-plan.md`.
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
