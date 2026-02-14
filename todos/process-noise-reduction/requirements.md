# Requirements: process-noise-reduction

## Goal

Eliminate "Process Noise" (worker complaints) by moving clerical verification logic from AI prompts into the Orchestrator engine and establishing `state.json` as the absolute Source of Truth.

## Success Criteria

- [ ] `teleclaude/core/next_machine/core.py` refactored to perform regex-based clerical checks (checkboxes) _before_ transitioning state.
- [ ] Transition logic in the engine relies purely on `state.json` values (`phase`, `build`, `review`).
- [ ] Worker command templates (`agents/commands/*.md`) stripped of "Verify prerequisites" and "Audit Build Gates" steps.
- [ ] Global lifecycle procedures updated to define "Verification" as an Orchestrator responsibility.
- [ ] Agent Primers updated to enforce the "Contract Trust" mandate.
- [ ] No worker should ever stop because a clerical checkbox is missing; the Orchestrator prevents the turn from starting if the state is incomplete.
