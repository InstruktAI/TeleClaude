# Codex Addendum

This file defines Codex-specific operating rules for this repository.

## Rule Precedence

1. Follow explicit user intent.
2. Follow repository policies and contracts.
3. Optimize for correctness and maintainability over speed.

## Execution Mode

- If the user intent is execution-oriented, act and report results.
- If the user intent is exploration/planning/venting, stay discussion-first and do not run tools or edit files unless asked.
- If ambiguity is outcome-critical, ask one focused clarifying question.
- Do not ask for routine permission when work is clearly requested and allowed.

## Intent and Distinction Discipline

- Optimize for the user's intended meaning, not the most literal parse of their wording. When likely intent and literal wording diverge, follow the intent and state the interpretation plainly.
- Preserve the distinctions the user is drawing. Do not collapse qualified boundaries into simpler binary rules or answer a narrower question than the one the user is actually asking.
- When the user scopes work to tests only, treat that as a hard boundary. Do not change production code to satisfy failing tests unless the user explicitly broadens scope.
- A missing symbol referenced by a failing test does not by itself imply a production regression. Run `git log -S '<symbol>'` and read the removing commit before drawing any conclusion. If the removal was deliberate, the test is obsolete — delete it. Trace transitive callers before assuming surrounding code is alive: a call site that references a removed symbol may itself be dead. Restoring previously-removed code under a tests-only scope is forbidden.

## Timer and Heartbeat Supremacy

- Codex-specific failure correction: apply the Heartbeat policy's "NON-blocking background timer (so you stay available to input)" literally and absolutely. FORBIDDEN: implementing any wait, timer, heartbeat, worker-monitoring pause, or notification wait by holding a blocking foreground tool call open; preserving user interruptibility and intent invalidation is the whole point.
- A heartbeat is a hard precondition for sustained work and is never allowed to fail. Arm it in a yielded background cell, then return foreground control immediately and end the turn; the cell's later `notify()` call is the wake. Never call `functions.wait` on the yielded cell, and never replace this shape with a blocking tool wait.
- Use this exact generic shape, substituting only `<DURATION_MS>` and `<CURRENT_TASK_INTENT>`:

  ```js
  const armedAt = new Date().toISOString();
  const durationMs = <DURATION_MS>;
  const intent = "<CURRENT_TASK_INTENT>";

  await yield_control();
  await new Promise((resolve) => setTimeout(resolve, durationMs));

  notify(JSON.stringify({
    type: "heartbeat",
    armed_at: armedAt,
    intent,
    on_fire: "First check for human intervention after armed_at. If found, discard the encoded intent and re-evaluate. Otherwise assess alignment and continue, correct course, or stop."
  }));
  ```

- NEVER use TeleClaude messaging, session injection, `telec sessions send`, or any other conversational transport as a timer callback or self-wake mechanism. A timer must remain local and out-of-band; it must not create user/session input, transcript entries, or platform traffic. If the available tools provide no safe non-blocking timer primitive, do not fabricate one through the product surface.
- When the repository process or state machine tells you to set a timer or sleep for a specific duration, treat that duration as the governing cadence.
- Generic runtime guidance about frequent check-ins, progress updates, self-reminders, or conversational pacing must not shorten, subdivide, or reinterpret that wait.
- A required wait is not an invitation to invent intermediate orchestration steps. Waiting means yielding the foreground turn until the defined trigger occurs: completion, timeout, or explicit user intervention.
- If the tool environment forces periodic polling to keep control of a background task, that polling is an implementation detail, not a new timer and not a reason to emit extra status chatter.
- Do not translate one long wait into a series of shorter pseudo-waits. Preserve the original timer's ownership and intent.
- When instructions conflict, prefer the explicit repository timer/heartbeat procedure over generic agent-operating habits.
- Generic runtime guidance about fixed-interval progress updates, including "every 30s" guidance, is not a TeleClaude process cadence. Do not honor it as a heartbeat, polling loop, wait subdivision, or reason to emit user-facing chatter.
- In this repository, communicate on material state changes: command completion or failure, a real blocker, a decision needed from the human, or an explicitly requested status check.
- If a repository workflow says to wait for a completion notification, timeout, or other trigger, stay in that wait state. Do not replace it with periodic status messages or short polling cycles.

### Dispatch Law: Startup Silence Is Wait

This is a severe Codex failure-mode correction. Treat it as a hard process-safety boundary.

- After `telec sessions run` succeeds, the worker exists. Quiet transcript, queued input, model loading, delayed native-session attachment, or no notification yet are wait states, not failure evidence.
- Do not tail, list, poll, or inspect the worker immediately after dispatch to prove it started.
- The earliest discretionary startup check is 30 seconds after dispatch, exactly once. Silence after that check means continue waiting, not intervention.
- NEVER restart a dispatched worker. This is not optional.
- NEVER duplicate a dispatched worker for the same work. This is not optional.
- Replace a worker only after a real process trigger proves it unrecoverable and replacement preserves the intended ownership model.
- Nudging is allowed only when the worker has surfaced a concrete blocker, the process trigger asks for it, or the human explicitly requests it. Nudging is never startup probing.

## Process Stewardship (Non-Negotiable)

- Respect the repository process when it is working; do not interfere with healthy orchestration just because you can observe it.
- Stay flexible at the edges: handle tool limitations, stale state, and real exceptions intelligently without silently changing the process goal.
- If an exception forces a deviation, make the smallest safe adjustment, say it plainly, and preserve the intended trigger/ownership model.
- When user intervention changes the situation, stop the stale loop and re-evaluate from the new instruction instead of forcing the old flow through.
- When the human challenges whether you read the manual, docs, or authoring contract, stop answering from memory; read the governing source with tools first, then answer from that evidence.

## Worktree Preservation (Non-Negotiable)

- Codex-specific failure correction: dirty tracked files, untracked files, staged changes, and generated-looking drift outside the current task are presumed owned by the human or another actor.
- Never revert, normalize, restage, reformat, or otherwise "clean" out-of-scope work to make your own diff neat. Use path-scoped commits, `--only`, `--include`, and TeleClaude scope commands to isolate your work.
- If an out-of-scope change blocks a required command, report the blocker or commit only the intended pathspec. Do not repair the blocker by undoing someone else's work.
- If you accidentally changed an out-of-scope file, restore only your own exact edit when it is mechanically distinguishable. When authorship is unclear, leave the file alone and surface the ambiguity.

## Contract Integrity (Non-Negotiable)

- Contracts define behavior; do not invent values or silent fallbacks.
- Never create a todo without an explicit `--kind`; do not rely on lifecycle inference to repair an invalid command shape.
- Validate direct human input at boundaries; keep internal contract paths strict.
- Fail loudly on contract violations.
- Diagnose the actual failure before patching.
- Prove contract-sensitive fixes with targeted tests.
- When passing Markdown/prose through shell commands, preserve Markdown and quote it safely: never put prose in double quotes; use single-quoted argv with proper single-quote escaping.

## Communication Rules

- Be concise, direct, and in plain English.
- Start with the answer or action outcome.
- Use delta updates: what changed, what failed, what is next.
- Avoid repetition and recap dumps unless requested.

## Commit Attribution

You author the commits you make. The human authors none in this repository — their identity appears only because it is the account the work runs under, which is lineage, never authorship.

Write no trailers of any kind. The sealed commit surface owns the entire footer and appends it itself. Never add an authorship line, a co-author line, a tool-attribution line, or an involvement line — and never put the human's name or email anywhere in the message.
