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
2. Receive the instruction block.
3. Execute the instructions verbatim. The state machine output is a linear script — follow it top-to-bottom without branching or decision-making.
4. When a notification arrives OR `orchestration-watch` fires, invoke the state machine again.
5. Repeat until the state machine emits a terminal cleanup script that includes `telec sessions end self`.

The state machine owns every concrete decision: dispatch, session ending, phase transitions, fix relay, terminal cleanup. The orchestrator never decides session lifecycle or branches on verdict — if the script says `telec sessions end <id>`, end that session; if the script says `telec sessions send <id> "..."`, send that message. The exception is `telec sessions end self` — the orchestrator's own departure, enacted through `session-departure` rather than run inline. The only orchestrator-owned behaviors are prescribed-reminder management and tailing discipline.

### Terminal Child Cleanup

<!-- planned-change:terminal-child-session-cleanup -->
The explicit worker IDs in a terminal state-machine script are immediate cleanup
instructions, not an exhaustive child inventory. After executing those lines and
before arming `session-departure`:

1. Run bare `telec sessions list` with no flags. Its default scope is every live
   session spawned by the current session.
2. End every session it returns with `telec sessions end <session_id>`.
3. Run bare `telec sessions list` again. Repeat cleanup until it returns no live
   children.

An orchestrator never substitutes `--all`, a job filter, remembered worker IDs,
or the state machine's explicit list for this caller-scoped enumeration. A child
that cannot be ended blocks self-departure; the owning session stays alive as the
signal. Only an empty bare listing satisfies the session-lifecycle requirement
that the dispatcher outlive and clean up all of its children.
<!-- change:terminal-child-session-cleanup -->
At a true terminal state, the state-machine script invokes bare `telec sessions
end` before self-departure. That operation owns caller-scoped enumeration and
closes every live direct child across computers; the orchestrator never expands
it into listing prose, remembered worker ids, or per-child commands. A failure
blocks self-departure, while a non-terminal handoff or resume emits no bulk
cleanup so the sessions needed for continuing work remain live.
<!-- /planned-change:terminal-child-session-cleanup -->

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

- `active`: the session is in a turn and its observed activity is advancing.
- `stalled`: the session is in a turn but its observed activity has been still beyond the platform's stall threshold. Treat this as a signal to inspect, not as completion — see Agent Degradation Handling.
- `idle`: the latest turn ended with an agent stop and no later input arrived.
- `unknown`: no activity has been recorded yet.

### When Notification Arrives

1. **Check for user intervention first.** If the user has sent messages, spoken to the worker directly, or changed direction since the worker was dispatched, pause and confirm with the user before proceeding. The notification's implicit instruction ("continue the loop") may be stale.
2. Tail the session (first time: default latest-turn window; subsequent tails: `--since <marker>`).
3. Update the marker to the latest message timestamp when new messages appear.
4. If `agent_status` is `active`, keep `orchestration-watch` live and continue waiting.
5. If `agent_status` is `idle`, invoke the state machine again (`telec todo work`, `telec todo prepare`, or `telec todo design` depending on the loop). Execute the returned script verbatim — it contains any durable state transitions, session-end commands, or `sessions send` relays for this exact moment.
6. If `agent_status` is `unknown`, continue waiting for the next event — unless the tail carries a readiness-investigation pointer, which means the session has not become live within its readiness budget. Then inspect, classify and adapt under Agent Degradation Handling instead of waiting further.
7. **Suppress no-op chatter.** Do not send no-op follow-up messages (`No new input`, `No further input`, `Remain idle`, `Continue standing by`). Only send `telec sessions send` when the state machine output explicitly instructs it.

### When `orchestration-watch` Fires

1. **Check for user intervention first.** If the user has sent messages, spoken to the worker directly, or changed direction since the reminder was set, its intent is stale — discard the encoded instructions and re-evaluate from the current state. Do not blindly resume the orchestration loop.
2. Tail the session (first time: default latest-turn window; subsequent tails: `--since <marker>`).
3. Update the marker to the latest message timestamp when new messages appear.
4. If `agent_status` is `active`, keep `orchestration-watch` live and continue waiting.
5. If `agent_status` is `idle`, invoke the state machine again and execute its returned script verbatim.
6. If `agent_status` is `unknown`, continue waiting for the next event — unless the tail carries a readiness-investigation pointer, which means the session has not become live within its readiness budget. Then inspect, classify and adapt under Agent Degradation Handling instead of waiting further.

### When Worker Needs Help

1. Cancel `orchestration-watch`.
2. Escalate to the human when the evidence shows a human-owned decision, an architectural
   choice, missing intent, repeated failed recovery attempts, or a worker unable to
   proceed from its own brief. Do not compose guidance and do not mutate code or tests
   yourself.
3. If resolution remains agent-owned, set `orchestration-watch` again and continue waiting. If escalation needs a human decision, leave it cancelled; the session is the beacon.
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

For a worker whose session derives `stalled` mid-turn (in a turn, activity still
beyond the stall threshold):

1. Capture the still-live pane with exactly:
   `tmux capture-pane -p -J -S - -t '<tmux_session_name>'`. Do not end the session.
2. Read the captured prose and classify. Only intelligence decides; silence alone
   establishes nothing.
3. When model-specific exhaustion is established, record the model the session's
   launch resolved to as unavailable with
   `telec agents status <agent> --model <model> --status unavailable --reason <reason> --until <iso8601>`,
   using the provider's stated recovery window. Never touch the agent-wide status.
4. Run `telec sessions restart <session_id>` once. The restart's computed launch
   resolves the next available chain model; the transcript and job context are
   preserved and the worker continues in place.
5. If the restart fails or the session stalls again for the same cause, perform no
   further model-quota recovery for that job. Keep the work pending for normal
   failure handling.
6. When the prose establishes a non-quota cause (a permission prompt, a wedged
   process, an unrelated error), handle it under the normal worker-help and
   escalation rules instead.

For direct evidence that explicitly establishes provider-wide quota, rate-limit,
credit, or instability:

1. Use `telec agents status <agent> --status <status> --reason <reason> [--until <iso8601>]`:
   - `status="degraded"` when the agent should be excluded from automatic fallback selection.
   - `status="unavailable"` for time-bounded outages or rate limits.
   - Use `--clear` when recovered.
2. Use the provider's stated recovery window for `--until`. Never invent a window.
3. Re-run `telec todo work ...` after the status update.
4. Do not delegate provider-status mutation to workers.

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

<!-- planned:review-round-cap-all-loops -->
When `telec todo prepare ...` returns `REVIEW_ROUND_LIMIT`, the orchestrator
cancels `orchestration-watch`, emits no reviewer dispatch or follow-up, and does
not stamp an exceptional verdict. It surfaces the capped phase, admitted-pass
count, and current findings to the human, then stays idle with the active
prepare session as the beacon. Preparation resumes only after the human
directly runs `telec todo stamp {slug} --review-round-override <phase>`; the
orchestrator then re-enters `telec todo prepare {slug}`, which admits the next
pass before the same gate closes again.

The same continuation gate applies when `telec todo work ...` reaches the
build-review limit with unresolved findings. The orchestrator preserves the
arithmetic verdict and stays idle; only a direct human
`--review-round-override build_review` stamp permits the next build-review pass.
The override never authorizes an approve verdict and must be repeated for
every later pass.
<!-- /planned:review-round-cap-all-loops -->

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

- If the worker stalls or reports a recoverable process failure, its own procedure carries the recovery mechanics; do not compose guidance. Escalate when it cannot proceed from its own brief.

## See Also

- ~/.teleclaude/docs/general/policy/orchestrator-jurisdiction.md — the process-state boundary an orchestrator operates inside.
