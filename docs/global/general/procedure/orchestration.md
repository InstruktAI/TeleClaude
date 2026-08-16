---
description: 'Orchestration loop for the next-work state machine and worker session handling.'
visibility: 'public'
---

# Orchestration — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/overview.md

## Goal

### Dispatch Rules

- **Reviewer thinking mode follows the review's scope.**
  - `fast` when the scope contains doc-snippet changes only.
  - `med` for every other review, including code-only and mixed code-and-doc scope.
  - `slow` is not used for reviewers.

  Context procedures state the resolved mode for their fixed scope; they do not
  choose a different mode.

### Review Quality Gate (Orchestrator-Owned)

Before accepting a review verdict, the orchestrator must verify the findings document is substantive:

1. Open `review-findings.md` and check that it contains at least one substantive analysis (not just positive observations).
2. For deliveries with 3+ tasks: if the review produces 0 Important+ findings, verify that a "Why no issues" justification section is present with specific evidence.
3. If either check fails, reject the review and re-dispatch at the mode the reviewer thinking-mode rule resolves for the scope.

This is a document-quality check, not a code review. The orchestrator does not review code — it verifies the reviewer did.

### Orchestration Loop

1. Invoke the state machine (`telec todo work {slug}`, `telec todo prepare [slug]`, or `telec todo design [slug]`) with the current target. Work orchestration is slug-scoped; do not call bare `telec todo work` to pick up unrelated work.
2. Receive the instruction block.
3. Execute the instructions verbatim. The state machine output is a linear script — follow it top-to-bottom without branching or decision-making.
<!-- planned-change:platform-reminder-service -->
4. When a notification arrives OR the heartbeat timer expires, invoke the state machine again.
<!-- change:platform-reminder-service -->
4. When a notification arrives OR `orchestration-watch` fires, invoke the state machine again.
<!-- /planned-change:platform-reminder-service -->
5. Repeat until the state machine emits a terminal cleanup script that includes `telec sessions end self`.

<!-- planned-change:platform-reminder-service -->
The state machine owns every concrete decision: dispatch, session ending, phase transitions, fix relay, terminal cleanup. The orchestrator never decides session lifecycle or branches on verdict — if the script says `telec sessions end <id>`, end that session; if the script says `telec sessions send <id> "..."`, send that message. The exception is `telec sessions end self` — the orchestrator's own departure, enacted per the Heartbeat policy rather than run inline. The only orchestrator-owned behaviors are heartbeat management and tailing discipline.
<!-- change:platform-reminder-service -->
The state machine owns every concrete decision: dispatch, session ending, phase transitions, fix relay, terminal cleanup. The orchestrator never decides session lifecycle or branches on verdict — if the script says `telec sessions end <id>`, end that session; if the script says `telec sessions send <id> "..."`, send that message. The exception is `telec sessions end self` — the orchestrator's own departure, enacted through `session-departure` rather than run inline. The only orchestrator-owned behaviors are prescribed-reminder management and tailing discipline.
<!-- /planned-change:platform-reminder-service -->

### Container Slug Handling

- Treat holder/container slugs as child-resolution entrypoints only. The holder itself is never a direct prepare/work target.
- Resolve direct children from roadmap `group_slug`. Never infer holder membership from slug prefixes, holder state, or `after` dependencies.
- Parent holder input is frozen source material for child seeding. The holder has no lifecycle state and no executable prepare/work artifacts.
- `telec todo prepare <holder>` emits `telec todo prepare <child>` only for dependency-satisfied direct children that still need preparation.
- `telec todo work <holder>` emits `telec todo work <child>` only for dependency-satisfied direct children that are ready for work or already in progress.
- Bare `telec todo work` is not a pickup loop. It emits a terminal self-end
  script because daemon-runner pickup, not a live orchestrator session, owns
  selecting future work.

### Tailing Discipline

The orchestrator maintains a **marker timestamp** per dispatched worker, initialized
to the dispatch time. All session inspection follows this protocol:

- **First tail** (after dispatch): use the default latest-turn window (`telec sessions tail <session_id>`) to establish context. Save the timestamp of the last message as the marker.
- **All subsequent tails**: use `--since <marker>` to retrieve only new output. This avoids re-reading content already seen and makes progress detection trivial — if `--since` returns no new messages, nothing happened.
- After every tail, update the marker to the latest message timestamp from the response.
- Each `telec sessions tail` response includes `last_input_at`, `last_activity`, `last_agent_stop_at`, and computed `agent_status`.

Status semantics:

- `active`: `last_activity` exists and the latest observed activity is not the agent stop event.
- `idle`: `last_activity` exists and `last_agent_stop_at == last_activity`.
- `unknown`: no `last_activity` has been recorded yet.

### When Notification Arrives

1. **Check for user intervention first.** If the user has sent messages, spoken to the worker directly, or changed direction since the worker was dispatched, pause and confirm with the user before proceeding. The notification's implicit instruction ("continue the loop") may be stale.
2. Tail the session (first time: default latest-turn window; subsequent tails: `--since <marker>`).
3. Update the marker to the latest message timestamp when new messages appear.
<!-- planned-change:platform-reminder-service -->
4. If `agent_status` is `active`, reset the heartbeat timer and continue waiting.
<!-- change:platform-reminder-service -->
4. If `agent_status` is `active`, keep `orchestration-watch` live and continue waiting.
<!-- /planned-change:platform-reminder-service -->
5. If `agent_status` is `idle`, invoke the state machine again (`telec todo work`, `telec todo prepare`, or `telec todo design` depending on the loop). Execute the returned script verbatim — it contains any durable state transitions, session-end commands, or `sessions send` relays for this exact moment.
6. If `agent_status` is `unknown`, continue waiting for the next event.
7. **Suppress no-op chatter.** Do not send no-op follow-up messages (`No new input`, `No further input`, `Remain idle`, `Continue standing by`). Only send `telec sessions send` when the state machine output explicitly instructs it.

<!-- planned-change:platform-reminder-service -->
### When Timer Expires
<!-- change:platform-reminder-service -->
### When `orchestration-watch` Fires
<!-- /planned-change:platform-reminder-service -->

1. **Check for user intervention first.** If the user has sent messages, spoken to the worker directly, or changed direction since the reminder was set, its intent is stale — discard the encoded instructions and re-evaluate from the current state. Do not blindly resume the orchestration loop.
2. Tail the session (first time: default latest-turn window; subsequent tails: `--since <marker>`).
3. Update the marker to the latest message timestamp when new messages appear.
<!-- planned-change:platform-reminder-service -->
4. If `agent_status` is `active`, reset the heartbeat timer and continue waiting.
<!-- change:platform-reminder-service -->
4. If `agent_status` is `active`, keep `orchestration-watch` live and continue waiting.
<!-- /planned-change:platform-reminder-service -->
5. If `agent_status` is `idle`, invoke the state machine again and execute its returned script verbatim.
6. If `agent_status` is `unknown`, continue waiting for the next event.

### When Worker Needs Help

<!-- planned-change:platform-reminder-service -->
1. Cancel old timer.
<!-- change:platform-reminder-service -->
1. Cancel `orchestration-watch` while direct recovery guidance is being prepared.
<!-- /planned-change:platform-reminder-service -->
2. Read the child's command instructions and role procedure before giving guidance, so the advice matches the child's actual responsibilities. If the failure was surfaced by the state machine before the child saw it, this read is what lets the orchestrator translate the state-machine failure into the child's next action.
3. Inspect enough evidence to classify the blocker: state-machine output, latest child tail, relevant artifacts, and worktree status when the failure is about merge, lint, tests, stamps, branch publication, or a dirty tree.
4. If the blocker is recoverable by the child, send concrete recovery guidance via `telec sessions send`: name the failed gate, explain the current context, point to the governing docs, state the expected end state, and return ownership to the child. Do not mutate code or tests yourself.
5. Escalate to the human only when the evidence shows a human-owned decision, an architectural choice, missing intent, or repeated failed recovery attempts.
<!-- planned-change:platform-reminder-service -->
6. Start new timer and continue waiting.
<!-- change:platform-reminder-service -->
6. Set `orchestration-watch` again and continue waiting.
<!-- /planned-change:platform-reminder-service -->
7. Do not send acknowledgement-only/no-op guidance.

### Agent Degradation Handling (Orchestrator-Owned)

A worker turn that produced no required work product is an unsuccessful outcome,
never a completion. The orchestrator tails, keeps the phase pending, and either
retries when there is a reason a retry would land differently, or reroutes
immediately when the provider is the problem. Silence establishes neither the
cause nor a provider status.

1. Mark provider status on any observed quota, rate-limit, credit, or
   provider-instability condition — at dispatch or inside a turn. Direct provider
   evidence is required; the provider's own error carries it, and its stated
   recovery window sets `--until`.
2. Use `telec agents status <agent> --status <status> --reason <reason> [--until <iso8601>]`:
   - `status="degraded"` when the agent should be excluded from automatic fallback selection.
   - `status="unavailable"` for time-bounded outages/rate limits.
   - Use `--clear` when recovered.
3. Re-run `telec todo work ...` after status update.
4. Do not delegate this decision to workers; only orchestrator should mutate provider status.

### Review Round Limit Handling (Orchestrator-Owned)

When `telec todo work ...` returns `REVIEW_ROUND_LIMIT`, the orchestrator does not
approve. The arithmetic-verdict rule from `lifecycle/work/review` applies at all
round counts — round limit is not an escape hatch and there is no Suggestion-tier
floor that lets unresolved findings pass.

1. Inspect current evidence:
   - `telec todo artifacts read {slug} review-findings`
   - Fix commits since `review_baseline_commit`
2. Decide and act:
   - If any unresolved **Requirement-Violation**, **Critical**, or **Important**
     finding remains, keep `review=changes_requested`. Record the blocker summary
     in `review-closure.md`. Sessions stay alive as signal for the human. The
     orchestrator does not stamp approve under any circumstance.
   - If every finding is resolved, mark `review=approved`. The verdict is
     arithmetic: zero unresolved findings means APPROVE.
   - If the loop is genuinely stuck (e.g. circular fix attempts, contradictory
     findings, or a violation no fix can address), escalate to the human with the
     accumulated findings and rationale. Do not invent a closure path.
3. Record rationale in todo artifacts so the closure is auditable.

The orchestrator must not rebrand Requirement-Violation, Critical, or Important
findings as "non-blocking", "follow-up", "suggestion", or any other reduced
category to reach approve. Per the review procedure severity schema, such
findings block regardless of round count. The schema has three tiers and every
tier blocks the verdict — there is no fourth tier and no deferral path.

- Point workers to the kind-resolved approved intent artifact, optional
  `architecture` when present, and `implementation-plan` for the execution
  spine. Historical `requirements` artifacts are readable but never a live
  fallback authority.

- Reference project docs or standards.
- Never dictate specific commands or code.

The loop terminates when the work state machine returns:

- `NO_CURRENT_WORK_SLUG` (no current slug was supplied; end the session)
- `COMPLETE`
- Non-recoverable error requiring intervention

<!-- planned:platform-reminder-service -->
#### Reminder: orchestration-watch

- **Owner:** Orchestration procedure.
- **Parameters:** lifecycle machine and target slug.
- **Activation anchor:** immediately before waiting for a dispatched worker or
  another lifecycle transition.
- **Duration:** the cadence emitted by the lifecycle state-machine formatter;
  the existing work formatter emits 300 seconds.
- **Recurrence:** recurring while the orchestration wait is active.
- **Arm condition:** set after the machine's current script has been executed and
  before control yields to a worker notification or time signal.
- **Intent:** `Re-enter <machine> for <slug> after checking for intervening human input. If the worker is active, inspect only new output; if it is idle, advance the state machine.`
- **Firing behavior:** apply the existing tailing discipline and execute the
  machine's returned script verbatim. A material notification may cause earlier
  re-entry without waiting for the reminder.
- **Cancellation:** cancel at the machine's terminal state, while blocked on a
  human decision, or when stale intent has no successor.
- **Invocation:** `telec reminders set orchestration-watch --machine <machine> --slug <slug>`.
<!-- /planned:platform-reminder-service -->

## Preconditions

- Work item state machine is available and in a known phase.
- Worker session is running or ready to be dispatched.

## Steps

1. Dispatch the worker with the appropriate state machine command.
<!-- planned-change:platform-reminder-service -->
2. Start a timer and wait for completion.
3. On timer expiry, inspect session output and decide next action.
<!-- change:platform-reminder-service -->
2. Set `orchestration-watch` and wait for completion or a material notification.
3. When the reminder fires, inspect session output and decide the next action under the rules above.
<!-- /planned-change:platform-reminder-service -->
4. Provide guidance using docs when workers are blocked.

## Outputs

- Work item progresses through phases with documented status.

## Recovery

- If the worker stalls or reports a recoverable process failure, mentor it back into motion with evidence-based guidance. Request a summary only when the current evidence is insufficient to issue useful recovery guidance.
