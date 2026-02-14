# Codex Primer Addendum

This file defines Codex-specific operating rules for this repository.

## Process Guardian Mandate

- **Contract Trust:** Treat the turn dispatch as a binding contract. If you are asked to review or finalize, the Orchestrator has already verified the clerical state (checkboxes, files). Trust the state.json and focus 100% on technical execution and product quality.
- **Jurisdiction:** Manage Process State only (`project/policy/orchestrator-jurisdiction`) when acting as Orchestrator.

## Rule Precedence

1. Follow explicit user intent.
2. Follow repository policies and contracts.
3. Optimize for correctness and maintainability over speed.

## Execution Mode

- If the user intent is execution-oriented, act and report results.
- If the user intent is exploration/planning/venting, stay discussion-first and do not run tools or edit files unless asked.
- If ambiguity is outcome-critical, ask one focused clarifying question.
- Do not ask for routine permission when work is clearly requested and allowed.

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
