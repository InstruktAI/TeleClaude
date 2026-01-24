---
id: architecture/next-machine
type: architecture
scope: global
description: Stateless state machine for orchestrating multi-phase project workflows.
---

# Next Machine Architecture

## Purpose

The Next Machine orchestrates complex development cycles (Phase A: Prepare, Phase B: Build/Review/Fix) without maintaining internal state.

## Inputs/Outputs

- Inputs: roadmap and work item artifacts (`roadmap.md`, `requirements.md`, `implementation-plan.md`, `state.json`).
- Outputs: explicit instructions or tool calls for the calling AI.

## Primary flows

1. **Statelessness**: It derives all work status from project artifacts:
   - `roadmap.md` (item discovery)
   - `requirements.md` and `implementation-plan.md` (preparation check)
   - `state.json` (build/review phase tracking)
2. **Phases**:
   - **Phase A (Prepare)**: HITL-heavy preparation of work items.
   - **Phase B (Work)**: Deterministic, autonomous implementation and verification.
3. **Execution**: It returns explicit instructions or tool calls for the calling AI to execute.

## Invariants

- Blocks claiming items with incomplete dependencies.
- Requires project files to be tracked by git for worktree accessibility.

## Failure modes

- Missing or malformed project artifacts prevent phase progression.
