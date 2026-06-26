---
description: 'TeleClaude mother-project governance for global agent artifacts: the agents/ global home, the AGENTS.global.md master, and agent addendum authoring. Universal artifact rules live in general/policy/agent-artifact-governance.'
visibility: 'public'
---

# Agent Artifact Governance — Policy

## Required reads

- @~/.teleclaude/docs/general/policy/agent-artifact-governance.md

## Rules

- The universal artifact-governance rules in `general/policy/agent-artifact-governance` apply in full. This policy adds only the mother-project specifics below and the addendum-authoring contract.
- The TeleClaude repo is the mother project for global artifacts. Only this repo may publish global artifacts from `agents/`.
- Global artifacts live under `agents/`; project-local artifacts live under `.agents/`.
- The global master file is `agents/AGENTS.global.md` and is only used for global artifacts.

### Agent addendum authoring

Addendum files (`agents/{AGENT}.addendum.md`) are thin behavioral shims for agent-specific failure modes. They are not documentation, not role definitions, and not context delivery mechanisms. Addenda exist only in this repository.

- **Failure-mode corrections only.** Every addendum item must answer: "What does this agent get wrong that others don't?" If all agents share the problem, extract it to a shared doc snippet.
- **No duplication.** If a behavior is already codified in a concept, policy, or procedure, do not repeat it. The context retrieval system delivers shared docs when needed.
- **No doc references.** No snippet IDs, no `@` paths, no inline references. Addenda are behavioral, not referential.
- **No role-specific content.** Role behavior (orchestrator, builder, reviewer) is loaded through command `Required reads`. Addenda apply to all sessions — role-specific content restricts the agent when it shouldn't.
- **Stay thin.** A growing addendum signals missing shared docs. Extract the general behavior into a shared snippet and keep only the agent-specific correction.

## Rationale

- A single mother project prevents drift and split-brain artifact sources.
- Addenda are confined to this repo because agent-specific failure-mode tuning belongs with the agent-artifact sources, not with adopting projects.

## Scope

- Applies to global artifact generation and distribution in this repository.

## Enforcement

- Global publishing is gated to this repo only.

## Exceptions

- None.
