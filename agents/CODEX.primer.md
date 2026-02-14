# Codex Primer Addendum

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

## Thinking-Mode Hard Guardrail

When the user explicitly says this is a thinking-only turn (for example: "thinking mode", "just reasoning", "no coding", "do not change anything", or similar), I must treat this as a stop-work trigger:

- Do not run tools.
- Do not edit files.
- Do not apply patches.
- Provide reasoning, diagnosis, and an execution-safe plan only.
- Never interpret this as permission to continue execution until the user explicitly says to proceed with changes.

Hard reminder to self:
`Thinking mode = NO_TOOLS, NO_EDITS, NO_PATCHES.`

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
- New policy/instruction text belongs in source primers/addenda, not generated files.

## Git Commit Addendum

Use this trailer in commits made by Codex:

`Co-Authored-By: Codex <noreply@openai.com>`

Commit behavior is governed by `@/Users/Morriz/.teleclaude/docs/software-development/policy/commits.md`.
