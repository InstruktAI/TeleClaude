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
4. When a notification arrives OR `orchestration-watch` fires, invoke the state machine again.
5. Repeat until the state machine emits a terminal cleanup script that includes `telec sessions end self`.

The state machine owns every concrete decision: dispatch, session ending, phase transitions, fix relay, terminal cleanup. The orchestrator never decides session lifecycle or branches on verdict — if the script says `telec sessions end <id>`, end that session; if the script says `telec sessions send <id> "..."`, send that message. The exception is `telec sessions end self` — the orchestrator's own departure, enacted through `session-departure` rather than run inline. The only orchestrator-owned behaviors are prescribed-reminder management and tailing discipline.

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
4. If `agent_status` is `active`, keep `orchestration-watch` live and continue waiting.
5. If `agent_status` is `idle`, invoke the state machine again (`telec todo work`, `telec todo prepare`, or `telec todo design` depending on the loop). Execute the returned script verbatim — it contains any durable state transitions, session-end commands, or `sessions send` relays for this exact moment.
6. If `agent_status` is `unknown`, continue waiting for the next event.
7. **Suppress no-op chatter.** Do not send no-op follow-up messages (`No new input`, `No further input`, `Remain idle`, `Continue standing by`). Only send `telec sessions send` when the state machine output explicitly instructs it.

### When `orchestration-watch` Fires

1. **Check for user intervention first.** If the user has sent messages, spoken to the worker directly, or changed direction since the reminder was set, its intent is stale — discard the encoded instructions and re-evaluate from the current state. Do not blindly resume the orchestration loop.
2. Tail the session (first time: default latest-turn window; subsequent tails: `--since <marker>`).
3. Update the marker to the latest message timestamp when new messages appear.
4. If `agent_status` is `active`, keep `orchestration-watch` live and continue waiting.
5. If `agent_status` is `idle`, invoke the state machine again and execute its returned script verbatim.
6. If `agent_status` is `unknown`, continue waiting for the next event.

### When Worker Needs Help

1. Cancel `orchestration-watch`.
2. Escalate to the human when the evidence shows a human-owned decision, an architectural
   choice, missing intent, repeated failed recovery attempts, or a worker unable to
   proceed from its own brief. Do not compose guidance and do not mutate code or tests
   yourself.
3. Set `orchestration-watch` again and continue waiting.
4. Do not send acknowledgement-only/no-op guidance.

### Agent Degradation Handling (Orchestrator-Owned)

<!-- planned-change:model-quota-slow-fallback -->
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
<!-- change:model-quota-slow-fallback -->
A worker turn that produced no required work product is an unsuccessful outcome,
never a completion. The orchestrator keeps the phase pending and distinguishes a
model-specific startup failure from a provider-wide failure. Silence establishes
neither cause.

For a startup failure that produced no native transcript:

1. Preserve the `session_id`, `tmux_session_name`, and literal original
   `telec sessions run` command returned or emitted at dispatch.
2. Capture the failed runtime before cleanup with exactly:
   `tmux capture-pane -p -J -S - -t '<tmux_session_name>'`.
3. Read the captured prose and determine whether it specifically establishes that
   the selected model exhausted its own quota while the provider may remain usable.
   Do not classify by keyword or infer a cause from silence.
4. When model-specific exhaustion is established, record the model the failed
   dispatch resolved to as unavailable with
   `telec agents status <agent> --model <model> --status unavailable --reason <reason> --until <iso8601>`.
   Use the provider's stated recovery window for `--until`; never invent a window.
   Never mutate the agent-wide status for model-specific exhaustion.
5. Run exactly `telec sessions end <session_id>` and wait for it to complete.
6. Repeat the literal original `telec sessions run` command once, completely
   unchanged. Mode-to-model resolution selects the next available entry in the
   agent's model chain; no mode argument changes.
7. If that retry fails — including a typed failure because every chain entry is
   unavailable — perform no further model-quota retry. Keep the work pending for
   normal failure handling.

For direct evidence that explicitly establishes provider-wide quota, rate-limit,
credit, or instability:

1. Use `telec agents status <agent> --status <status> --reason <reason> [--until <iso8601>]`:
   - `status="degraded"` when the agent should be excluded from automatic fallback selection.
   - `status="unavailable"` for time-bounded outages or rate limits.
   - Use `--clear` when recovered.
2. Use the provider's stated recovery window for `--until`. Never invent a window.
3. Re-run `telec todo work ...` after the status update.
4. Do not delegate provider-status mutation to workers.
<!-- /planned-change:model-quota-slow-fallback -->

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

## Preconditions

- Work item state machine is available and in a known phase.
- Worker session is running or ready to be dispatched.

## Steps

1. Dispatch the worker with the appropriate state machine command.
2. Set `orchestration-watch` and wait for completion or a material notification.
3. When the reminder fires, inspect session output and decide the next action under the rules above.
4. Provide guidance using docs when workers are blocked.

## Outputs

- Work item progresses through phases with documented status.

## Recovery

- If the worker stalls or reports a recoverable process failure, its own procedure carries the recovery mechanics; do not compose guidance. Escalate when it cannot proceed from its own brief.
