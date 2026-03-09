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

## Worker Orchestration Discipline

- When orchestrating worker sessions, dispatch and then wait for completion notification/timeout before acting again.
- Do not proactively tail, ping, or steer workers unless a timeout fires, the worker asks a direct question, or the user explicitly requests intervention.
- Do not close or restart an active worker session just to accelerate; only intervene on explicit stall/error signals or user direction.

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

## Artifact Editing Rule (Non-Negotiable)

- Never edit generated artifacts directly: `AGENTS.md`, `CLAUDE.md`, `CODEX.md`.
- Edit source artifact files under `agents/` (or other declared source paths) only.
- If a generated artifact is edited by mistake, revert it immediately and re-apply the change to source.
- New policy/instruction text belongs in source addenda, not generated files.

## Git Commit Addendum

Use this trailer in commits made by Codex:

`Co-Authored-By: Codex <noreply@openai.com>`

Commit behavior is governed by `@/Users/Morriz/.teleclaude/docs/software-development/policy/commits.md`.
