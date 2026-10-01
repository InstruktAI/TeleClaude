---
description: 'TeleClaude mother-project governance for global agent artifacts: the agents/ global home, the AGENTS.global.md master, and agent addendum authoring. Universal artifact rules live in general/policy/agent-artifact-governance.'
visibility: 'public'
---

# Agent Artifact Governance — Policy

## Required reads

- @~/.teleclaude/docs/general/policy/agent-artifact-governance.md

## Rules

- The universal artifact-governance rules in `general/policy/agent-artifact-governance` apply in full. This policy adds only the mother-project specifics below and the addendum-authoring contract.
- The TeleClaude repo is the mother project for global artifact governance. Only this repo publishes the global master, global skills, addenda, and catalog instructions. It publishes the `general` domain — its documentation and its commands — because it declares `general` in `business.publishes`, exactly as every domain-partitioned global command publishes from the one repository that declares its domain.
- Every skill entrypoint keeps the universal name, description, and folder-identity contract. Package bodies retain their upstream structure.
- The mother alone owns the skill catalog master at `agents/global/skills/AGENTS.master.md` and every global skill folder beside it. A side project's global skill folders and catalog master are refused at validation; a portable skill a side project authors is contributed to the mother, which is the curation step.
- The Mother-owned skill catalog master is a thin orientation wrapper for the catalog directory. It carries no index and no executable directives; the catalog listing is rendered on demand by `general/procedure/skill-use`.
- This repository owns the agent runtime settings TeleClaude deploys, and with them the Claude Code project-instructions setting that makes every generated `AGENTS.md` load beside any `CLAUDE.md` in its directory or above. That setting is user-scope only, so the deployed Claude user settings are its one carrier; no repository and no home reaches Claude Code's `AGENTS.md` reading through a generated `CLAUDE.md`.
- Every repository carries `agents/{global,local}/{commands,skills}`. This repository, as the mother, fills `agents/global/` in full; a side project fills `agents/local/` freely and `agents/global/commands/<domain>/` only for domains it publishes. `.agents/` is a delivery location, never a source, under the separation the global policy states. The global master and the addenda are not artifact kinds and are not tiered: they stay at the artifact root as `agents/AGENTS.global.md` and `agents/<AGENT>.addendum.md`.
- The global master file is `agents/AGENTS.global.md` and is only used for global artifacts. Its baseline is the `general` domain's generated bundle, named as a Required read like any other domain bundle; the general baseline index and the general activatable procedures reach every global agent configuration through that bundle.

### Agent addendum authoring

Addendum files (`agents/{AGENT}.addendum.md`) are thin behavioral shims for agent-specific failure modes. They are not documentation, not role definitions, and not context delivery mechanisms. Addenda exist only in this repository.

- **Failure-mode corrections only.** Every addendum item must answer: "What does this agent get wrong that others don't?" If all agents share the problem, extract it to a shared doc snippet.
- **No duplication.** If a behavior is already codified in a concept, policy, or procedure, do not repeat it. The context retrieval system delivers shared docs when needed.
- **No doc references.** No snippet IDs, no `@` paths, no inline references. Addenda are behavioral, not referential.
- **No role-specific content.** Role behavior (orchestrator, builder, reviewer) is loaded through command `Required reads`. Addenda apply to all sessions — role-specific content restricts the agent when it shouldn't.
- **Stay thin.** A growing addendum signals missing shared docs. Extract the general behavior into a shared snippet and keep only the agent-specific correction.

## Rationale

- A single mother-owned catalog definition prevents split-brain global instructions, and routing every global skill through the mother's own folders makes the catalog the one curation surface rather than a merge of publishers.
- Rendering the catalog after assembling its links lets the human-authored source describe the real deployed catalog without preloading that catalog into every agent baseline.
- Whether a runtime reads the generated entrypoint at all is decided by that runtime's own settings. Carrying the deciding setting in the settings this repository deploys keeps one entrypoint per directory working under every ancestor layout, without editing files the human or another repository owns.
- Addenda are confined to this repo because agent-specific failure-mode tuning belongs with the agent-artifact sources, not with adopting projects.
- `general` is declared, not implied, so one ownership rule covers every domain: publication, bundle generation, command reach and the domain roster all read the declaration, and no code path carries a named exception that can drift from it.

## Scope

- Applies to global artifact generation and distribution in this repository.

## Enforcement

- Global skills publish from this repository alone; a domain command, `general` included, publishes only from the repository that declares its domain. A global source outside a repository's reach is refused at validation with a finding naming the file and the reach it exceeds.
- Side-project skill catalog masters and generated catalog entrypoints are excluded from publication; the Mother-owned catalog is the only catalog instruction source.
- Published third-party skill package bodies and supporting Markdown are never rejected for failing TeleClaude artifact section or heading rules; their `SKILL.md` identity metadata is still required.

## Exceptions

- None.
