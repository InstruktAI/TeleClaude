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

## Worker Orchestration Discipline

- When orchestrating worker sessions, dispatch and then wait for completion notification/timeout before acting again.
- Do not proactively tail, ping, or steer workers unless a timeout fires, the worker asks a direct question, or the user explicitly requests intervention.
- Do not close or restart an active worker session just to accelerate; only intervene on explicit stall/error signals or user direction.

## Timer and Heartbeat Supremacy

- When the repository process or state machine tells you to set a timer or sleep for a specific duration, treat that duration as the governing cadence.
- Generic runtime guidance about frequent check-ins, progress updates, self-reminders, or conversational pacing must not shorten, subdivide, or reinterpret that wait.
- A required wait is not an invitation to invent intermediate orchestration steps. Stay in the wait state until the defined trigger occurs: completion, timeout, or explicit user intervention.
- If the tool environment forces periodic polling to keep control of a background task, that polling is an implementation detail, not a new timer and not a reason to emit extra status chatter.
- Do not translate one long wait into a series of shorter pseudo-waits. Preserve the original timer's ownership and intent.
- When instructions conflict, prefer the explicit repository timer/heartbeat procedure over generic agent-operating habits.
- Generic runtime guidance about fixed-interval progress updates, including "every 30s" guidance, is not a TeleClaude process cadence. Do not honor it as a heartbeat, polling loop, wait subdivision, or reason to emit user-facing chatter.
- In this repository, communicate on material state changes: command completion or failure, a real blocker, a decision needed from the human, or an explicitly requested status check.
- If a repository workflow says to wait for a completion notification, timeout, or other trigger, stay in that wait state. Do not replace it with periodic status messages or short polling cycles.

## Process Stewardship (Non-Negotiable)

- Respect the repository process when it is working; do not interfere with healthy orchestration just because you can observe it.
- Stay flexible at the edges: handle tool limitations, stale state, and real exceptions intelligently without silently changing the process goal.
- If an exception forces a deviation, make the smallest safe adjustment, say it plainly, and preserve the intended trigger/ownership model.
- When user intervention changes the situation, stop the stale loop and re-evaluate from the new instruction instead of forcing the old flow through.

## Contract Integrity (Non-Negotiable)

- Contracts define behavior; do not invent values or silent fallbacks.
- Validate direct human input at boundaries; keep internal contract paths strict.
- Fail loudly on contract violations.
- Diagnose the actual failure before patching.
- Prove contract-sensitive fixes with targeted tests.

## Communication Rules

- Be concise, direct, and in plain English.
- Start with the answer or action outcome.
- Use delta updates: what changed, what failed, what is next.
- Avoid repetition and recap dumps unless requested.

## `telec code commit` Addendum

Use this trailer in commits made by Codex:

`Co-Authored-By: Codex <noreply@openai.com>`
