---
description: 'TeleClaude mother-project governance for global agent artifacts: the agents/ global home, the AGENTS.global.md master, and agent addendum authoring. Universal artifact rules live in general/policy/agent-artifact-governance.'
visibility: 'public'
---

# Agent Artifact Governance — Policy

## Required reads

- @~/.teleclaude/docs/general/policy/agent-artifact-governance.md

## Rules

- The universal artifact-governance rules in `general/policy/agent-artifact-governance` apply in full. This policy adds only the mother-project specifics below and the addendum-authoring contract.
- The TeleClaude repo is the mother project for global artifact governance. Only this repo may publish the global master, commands, agents, addenda, and catalog instructions from `agents/`.
<!-- planned-change:drop-skill-taxonomy-optin -->
- Every registered project may publish human-curated global skill folders from `agents/skills/<name>/`; the folder's existence is the publication declaration. Every entrypoint keeps the universal name, description, and folder-identity contract. Package bodies retain their upstream structure unless `SKILL.md` explicitly declares `teleclaude_taxonomy: true`.
<!-- change:drop-skill-taxonomy-optin -->
- Every registered project may publish human-curated global skill folders from `agents/skills/<name>/`; the folder's existence is the publication declaration. Every entrypoint keeps the universal name, description, and folder-identity contract. Package bodies retain their upstream structure.
<!-- /planned-change:drop-skill-taxonomy-optin -->
- The Mother project alone owns `agents/skills/AGENTS.master.md`. A side project's `agents/skills/AGENTS.master.md` or generated `AGENTS.md` is never parsed or published; only its named skill folders contribute.
- The Mother-owned skill catalog master is a thin orientation wrapper for the catalog directory. It carries no index and no executable directives; the catalog listing is rendered on demand by `general/procedure/skill-use`.
<!-- planned-change:agent-artifact-source-layout -->
- Global artifact sources live under `agents/`; project-local artifacts live under `.agents/`.
<!-- change:agent-artifact-source-layout -->
- Every repository carries `agents/{global,project}/{agents,commands,skills}`. This repository, as the mother, fills `agents/global/` in full; a side project fills `agents/project/` freely and `agents/global/commands/<domain>/` only for domains it publishes. `.agents/` is a delivery location, never a source, under the separation the global policy states.
<!-- /planned-change:agent-artifact-source-layout -->
- The global master file is `agents/AGENTS.global.md` and is only used for global artifacts.

### Agent addendum authoring

Addendum files (`agents/{AGENT}.addendum.md`) are thin behavioral shims for agent-specific failure modes. They are not documentation, not role definitions, and not context delivery mechanisms. Addenda exist only in this repository.

- **Failure-mode corrections only.** Every addendum item must answer: "What does this agent get wrong that others don't?" If all agents share the problem, extract it to a shared doc snippet.
- **No duplication.** If a behavior is already codified in a concept, policy, or procedure, do not repeat it. The context retrieval system delivers shared docs when needed.
- **No doc references.** No snippet IDs, no `@` paths, no inline references. Addenda are behavioral, not referential.
- **No role-specific content.** Role behavior (orchestrator, builder, reviewer) is loaded through command `Required reads`. Addenda apply to all sessions — role-specific content restricts the agent when it shouldn't.
- **Stay thin.** A growing addendum signals missing shared docs. Extract the general behavior into a shared snippet and keep only the agent-specific correction.

## Rationale

- A single mother-owned catalog definition prevents split-brain global instructions while registered projects remain free to contribute human-curated skill packages by folder.
- Rendering the catalog after assembling its links lets the human-authored source describe the real deployed catalog without preloading that catalog into every agent baseline.
- Addenda are confined to this repo because agent-specific failure-mode tuning belongs with the agent-artifact sources, not with adopting projects.

## Scope

- Applies to global artifact generation and distribution in this repository.

## Enforcement

- Global publishing outside `agents/skills/<name>/` is gated to this repo only.
- Side-project skill catalog masters and generated catalog entrypoints are excluded from publication; the Mother-owned catalog is the only catalog instruction source.
- Published third-party skill package bodies and supporting Markdown are never rejected for failing TeleClaude artifact section or heading rules; their `SKILL.md` identity metadata is still required.

## Exceptions

- None.
