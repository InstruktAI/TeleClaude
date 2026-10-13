---
description: 'Orchestration loop for the work state machine and worker session handling.'
visibility: 'public'
---

# Orchestration — Procedure

## Required reads

- @~/.teleclaude/docs/sdlc/procedure/lifecycle/overview.md

## Goal

### Dispatch Rules

- **Reviewer thinking mode follows the review's scope.**
  - `med` when the scope contains doc-snippet changes only.
  - `slow` for commit reviews containing code, including mixed code-and-doc scope, and for other reviews.

  Context procedures state the resolved mode for their fixed scope; they do not
  choose a different mode.

### Review Quality Gate (Orchestrator-Owned)

The workflow boundary refuses every preparation or build verdict unless the
phase-specific report exists and binds its current digest together with the
current reviewed target. The orchestrator verifies the report's substance:

1. Open the current phase-specific report and confirm every required review
   lane or preparation-review section is present with substantive analysis.
2. When the review reports zero Important-or-higher findings, verify the
   required `Why No Issues` evidence is specific to the target.
3. If either check fails, reject the review and re-dispatch at the mode the
   reviewer thinking-mode rule resolves for the scope.

This is a document-quality check, not a second code or artifact review. Digest
binding proves which report exists; the orchestrator verifies that the reviewer
actually did the work recorded there.

### Orchestration Loop

1. Invoke the state machine (`telec todo work {slug}`, `telec todo prepare [slug]`, or `telec todo design [slug]`) with the current target. Work orchestration is slug-scoped; do not call bare `telec todo work` to pick up unrelated work.

2. Receive the instruction block. The call returns an operation receipt and does not wait for the machine. Yield; when the operation's outcome wakes this session, read the instruction block from the operation record with `telec operations get <operation_id>`.

3. Execute the machine-owned lifecycle commands in their returned order. Before execution and after each worker observation, reconcile the script with current human input and evidence under `general/procedure/ai-to-ai-operations` and `general/policy/human-contract`; apply the recovery sections below when the observed condition prevents that execution.
4. When a notification arrives OR `orchestration-watch` fires, assess it under the corresponding section below. Re-enter the state machine when that assessment calls for continuation; attention is not itself a completed worker turn.
5. Repeat until the state machine emits a terminal handoff or cleanup script. Terminal completion closes the workflow assignment; the session's remaining obligations and departure follow `general/principle/session-lifecycle`.

The state machine owns lifecycle sequencing, dispatch, phase transitions, fix
relay, and terminal worker cleanup. The orchestrator owns current-evidence
assessment, recovery routing, and the remaining obligations of its own session
under `general/procedure/ai-to-ai-operations`,
`general/principle/session-lifecycle`, and `general/policy/human-contract`.
That judgment never substitutes for an independent verdict or authorizes a
lifecycle mutation outside the supported surface.

### Terminal Child Cleanup

At a true terminal state, the state-machine script invokes bare `telec sessions
end` as terminal worker cleanup. That operation owns caller-scoped enumeration and
closes every live direct child across computers; the orchestrator never expands
it into listing prose, remembered worker ids, or per-child commands. A failure
blocks self-departure, while a non-terminal handoff or resume emits no bulk
cleanup so the sessions needed for continuing work remain live.

A terminal handoff that passes the todo's next move to another owner releases
the orchestrator's lifecycle claim on that todo at the handoff, so the next
owner takes it up whether or not this session remains open. Successful worker
cleanup leaves the orchestrator to assess every remaining session obligation
before departure. An unfinished human conversation keeps the session open,
never the claim; a terminal workflow script settles only its assignment
(`general/principle/session-lifecycle`, `general/principle/attunement`).

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
to the dispatch time. Transcript inspection follows this protocol; event and
live-pane observations are separate evidence:

- **First tail** (after dispatch): use the default latest-turn window (`telec sessions tail <session_id>`) to establish context. Save the timestamp of the last message as the marker.
- **All subsequent tails**: use `--since <marker>` to retrieve only new output. No new messages means only that this query returned no new transcript content; a notification or pane-only condition may still require action.
- After every tail, update the marker to the latest message timestamp from the response.
- Each `telec sessions tail` response includes `last_input_at`, `last_activity`, `last_agent_stop_at`, and computed `agent_status`.

Respond by `agent_status`:

- `active` or `unknown`: keep waiting for the next event.
- `idle`: the turn ended; continue the loop.
- `blocked`: handle it under When Worker Needs Help; the same turn continues once the wait is resolved.
- `stalled`: handle it under Agent Degradation Handling; the turn does not continue on its own.

### When Notification Arrives

1. **Check for user intervention first.** If the user has sent messages, spoken to the worker directly, or changed direction since the worker was dispatched, pause and confirm with the user before proceeding. The notification's implicit instruction ("continue the loop") may be stale.
2. Read the notification's reported event and native evidence. Fetch `general/procedure/ai-to-ai-operations` with `telec docs get` when it is not already loaded, then apply its parent-assessment steps. Inspect the live pane when the observation requires it, even if session metadata and transcript are unchanged.
3. Tail for conversational context as needed (first time: default latest-turn window; subsequent tails: `--since <marker>`). Update the marker only when new timestamped messages appear.
4. For a reported permission/input wait, failure, or an obstruction established by current evidence, follow When Worker Needs Help and Agent Degradation Handling as applicable. Neither `active` nor an empty tail is a reason to ignore the observation. A reported wait carries the provider's own cause and message text as evidence; assess from that before inspecting the emitting session.

5. For a completion, assess the produced result under the existing role contract. If continuation is due, invoke the state machine again (`telec todo work`, `telec todo prepare`, or `telec todo design` depending on the loop), receive its script as Orchestration Loop step 2 describes, and execute it verbatim. A failed or blocked turn is not promoted to successful completion by this step.

6. If assessment establishes valid waiting, maintain the applicable watch under the reminder policy.
7. **Suppress no-op chatter.** Do not send no-op follow-up messages (`No new input`, `No further input`, `Remain idle`, `Continue standing by`). Only send `telec sessions send` when the state machine output explicitly instructs it.

### When `orchestration-watch` Fires

Apply the same evidence distinction as notification handling. An unresolved
attention observation or current pane evidence is not settled by an unchanged
transcript or an `active` status; assess it under When Worker Needs Help or
Agent Degradation Handling before the ordinary waiting/continuation branches
below. This does not change the watch's cadence or the recovery owner's powers.

1. **Check for user intervention first.** If the user has sent messages, spoken to the worker directly, or changed direction since the reminder was set, its intent is stale — discard the encoded instructions and re-evaluate from the current state. Do not blindly resume the orchestration loop.
2. Tail the session (first time: default latest-turn window; subsequent tails: `--since <marker>`).
3. Update the marker to the latest message timestamp when new messages appear.
4. If `agent_status` is `active`, keep `orchestration-watch` live and continue waiting.
5. If `agent_status` is `idle`, invoke the state machine again and execute its returned script verbatim.
6. If `agent_status` is `unknown`, continue waiting for the next event. A session that does not start within its startup window becomes `stalled` and notifies you.
7. If `agent_status` is `blocked` or `stalled`, handle it under When Worker Needs Help or Agent Degradation Handling.

### When Worker Needs Help

1. Cancel `orchestration-watch`.
2. Classify the remaining decision under `general/policy/human-contract`.
   Route technical recovery to the responsible agent with the evidence and
   governing addresses. An architectural question, repeated failed attempts,
   or an exhausted brief does not itself make the decision human-owned.
   Do not author the worker's code or tests. Escalate to the human only with
   the specific human-owned decision or safety gate that prevents progress.
3. Record the next contribution and its owner. If the orchestrator retains a
   gated next move, set `orchestration-watch` again before waiting. If the next
   move belongs elsewhere, leave it cancelled; preserve the routed blocker.
4. Do not send acknowledgement-only/no-op guidance.

### Agent Degradation Handling (Orchestrator-Owned)

A worker turn that produced no required work product is an unsuccessful outcome,
never a completion. The orchestrator keeps the phase pending and distinguishes a
model-specific startup failure from a provider-wide failure. Silence establishes
neither cause.

A failed or exhausted attempt to deliver input establishes only that the input
did not reach the agent. It does not establish that the agent process is dead,
that the session cannot continue, or that its lifecycle claim may be released.
Treat the delivery result as the trigger for the same inspect-classify-adapt
discipline below: inspect the session and its native evidence, identify the
actual obstruction, change approach where the evidence warrants it, and retry
only through the sanctioned recovery path. File a platform gap only when that
path itself fails; never replace the investigation with automatic end and
redispatch of a session that may encounter the same condition again.

For a non-quota startup failure whose command delivery has terminated:

1. Cancel `orchestration-watch`. Preserve the session identity, owning computer,
   and literal original `telec sessions run` command. Inspect the session,
   native evidence, and delivery result under
   `general/procedure/ai-to-ai-operations`; establish whether the command reached
   the worker and whether startup delivery is still pending or has terminated.
   A live process or visible composer does not establish a usable task dispatch.
2. Resolve the established setup obstruction within the existing mandate.
   Accept workspace trust under `sdlc/policy/ai-agent-security`; assess other
   permission requests under `general/procedure/ai-to-ai-operations` and
   `general/policy/human-contract`. Clearing a prompt completes setup only;
   it does not establish command delivery or resume a terminated delivery.
3. Before closing, inspect and preserve any work product, durable state, and
   outstanding child obligations under `general/principle/session-lifecycle`.
   If the command reached the worker and task execution began, use the
   executing-worker recovery path instead. When the command was not delivered
   and startup delivery has terminated, treat that dispatch as unusable even
   if its process remains live.
4. Run `telec sessions end <session_id>` on the owning computer and confirm
   closure before creating a replacement. Repeat the original dispatch with
   its command, arguments, project, subfolder, and thinking mode preserved;
   apply an explicitly directed agent change when present. Keep the lifecycle
   phase pending; replacement does not advance it.
5. Save the replacement session identity and initialize its tail marker.
   Arm `orchestration-watch` for the target slug before yielding, then assess
   the replacement's events under the notification and tailing discipline.
   Confirm actual task start from runtime evidence; dispatch acceptance alone
   is not recovery completion (`general/procedure/ai-to-ai-operations`).
6. If the replacement fails, reassess the new evidence and its next recovery
   contribution under `general/policy/human-contract`; do not repeat an
   unchanged failed recovery without resolving its cause.

For a model-quota startup failure that produced no native transcript:

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

For a worker whose session is `stalled`:

1. Read the notification's evidence first. A runtime-reported failure carries the
   provider's own payload, which often establishes the cause. When it does not,
   or the stall was inferred, capture the still-live pane with exactly:
   `tmux capture-pane -p -J -S - -t '<tmux_session_name>'`. Do not end the session
   before this assessment.
2. Read the evidence and classify. Only intelligence decides; silence alone
   establishes nothing.
3. When model-specific exhaustion is established, record the model the session's
   launch resolved to as unavailable with
   `telec agents status <agent> --model <model> --status unavailable --reason <reason> --until <iso8601>`,
   using the provider's stated recovery window. Never touch the agent-wide status.
4. For that model-specific exhaustion, run `telec sessions restart <session_id>`
   once. The restart's computed launch
   resolves the next available chain model; the transcript and job context are
   preserved and the worker continues in place.
5. If the restart fails or the session stalls again for the same cause, perform no
   further model-quota recovery for that job. Keep the work pending for normal
   failure handling.
6. When the prose establishes a non-quota cause (a permission prompt, a wedged
   process, an unrelated error), distinguish failed startup delivery from an
   executing worker's obstruction. Apply the terminated startup-delivery path
   above when its conditions hold; otherwise use When Worker Needs Help.

For direct evidence that explicitly establishes provider-wide quota, rate-limit,
credit, or instability:

1. Use `telec agents status <agent> --status <status> --reason <reason> [--until <iso8601>]`:
   - `status="degraded"` when the agent should be excluded from automatic fallback selection.
   - `status="unavailable"` for time-bounded outages or rate limits.
   - Use `--clear` when recovered.
2. Use the provider's stated recovery window for `--until`. Never invent a window.
3. Re-run `telec todo work ...` after the status update.
4. Do not delegate provider-status mutation to workers.

### Review Threshold Handling (Orchestrator-Owned)

When a preparation or work review reaches its documented threshold, the count
is reported once and nothing is refused. Continuation stays with this
orchestrator: it requests another pass only when it can establish what remains
unresolved and why the next act resolves it within the frozen scope
(`sdlc/procedure/lifecycle/review`). The reviewer retains its verdict, the
producer retains its finding dispositions, and this orchestrator retains
lifecycle execution and state mutation.
`general/policy/human-contract` governs any escalation.

1. Inspect current evidence:
   - `telec todo artifacts read {slug} review-findings`
   - Fix commits since `review_baseline_commit`
2. Decide and act:
   - If any unresolved **Requirement-Violation**, **Critical**, or **Important**
     finding remains, keep `review=changes_requested`. Record the blocker summary
     in the phase-specific review artifact. Preserve the required sessions
     and name the next contribution's agent owner. No approve is stamped
     while a finding remains unresolved.
   - If every finding is resolved, mark `review=approved`. The verdict is
     arithmetic: zero unresolved findings means APPROVE.
   - If the loop is stuck or its remediation has become disproportionate to the
     concern, stop continuation, record the grounded cause, and route the next
     contribution under the shared review procedure. A technical recovery,
     return to an owning phase, or further bounded review does not require
     human approval. A decision in the closed human lane does.
3. Record rationale in todo artifacts so the closure is auditable.

When an orchestrator or human closes any preparation or build review through a
sanctioned recovery or owner-directed path, the closing party first writes the
complete phase-specific report. The report records the closure rationale and
the evidence that authorizes that exceptional verdict path; only then may the
party stamp the verdict. Orchestrator recovery authority is unchanged, but it
never creates an evidence-free stamp.

The orchestrator must not rebrand Requirement-Violation, Critical, or Important
findings as "non-blocking", "follow-up", "suggestion", or any other reduced
category to reach approve. Per the review procedure severity schema, such
findings block regardless of round count. The schema has three tiers and every
tier blocks the verdict — there is no fourth tier and no deferral path.

Reminder ownership follows `general/policy/reminder`; a crossed threshold never
transfers the next move to the human.

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
- **Parameters:** target slug.
- **Activation anchor:** immediately before waiting for a dispatched worker or
  another lifecycle transition.
- **Duration:** the cadence emitted by the lifecycle state-machine formatter;
  the existing work formatter emits 300 seconds.
- **Recurrence:** recurring while the orchestration wait is active.
- **Arm condition:** set after the machine's current script has been executed and
  before control yields to a worker notification or time signal.
- **Intent:** `Re-enter the state machine for <slug> after checking for intervening human input. If the worker is active, inspect only new output; if it is idle, advance the state machine.`
- **Firing behavior:** apply the existing tailing discipline and execute the
  machine's returned script verbatim. A material notification may cause earlier
  re-entry without waiting for the reminder.
- **Cancellation:** cancel at the machine's terminal state, while blocked on a
  human decision, or when stale intent has no successor.
- **Invocation:** `telec reminders set orchestration-watch --slug <slug>`.

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

- Route startup-dispatch failures through Agent Degradation Handling and
  recovery inside an executing worker's brief through When Worker Needs Help.

## See Also

- ~/.teleclaude/docs/general/procedure/ai-to-ai-operations.md — role-independent parent attention and current-evidence assessment.
- ~/.teleclaude/docs/general/policy/orchestrator-jurisdiction.md — the process-state boundary an orchestrator operates inside.
