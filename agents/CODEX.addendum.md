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

### Dispatch Law: Startup Silence Is Wait

This is a severe Codex failure-mode correction. Treat it as a hard process-safety boundary.

- After `telec sessions run` succeeds, the worker should exist. Quiet transcript, queued input, model loading, delayed native-session attachment, or no notification yet are wait states, not failure evidence.
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
- **Durable-operation invocation uses a 600-second outer yield.** When a CLI owns polling a durable receipt, invoke it with a 600-second outer yield — the poller's terminal bound — never the shorter default. Never treat an early yield as completion or take over receipt polling.

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
- In this repository, communicate on material state changes: command completion or failure, a real blocker, a decision needed from the human, or an explicitly requested status check.
- Avoid repetition and recap dumps unless requested.

## Commit Attribution

You author the commits you make. The human authors none in this repository — their identity appears only because it is the account the work runs under, which is lineage, never authorship.

Write no trailers of any kind. The sealed commit surface owns the entire footer and appends it itself. Never add an authorship line, a co-author line, a tool-attribution line, or an involvement line — and never put the human's name or email anywhere in the message.
