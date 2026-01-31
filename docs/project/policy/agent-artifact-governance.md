---
id: project/policy/agent-artifact-governance
type: policy
scope: project
description: Governance rules for agent artifact sources, transforms, and ownership.
---

# Agent Artifact Governance — Policy

## Rules

- The TeleClaude repo is the mother project for global artifacts. Only this repo may publish global artifacts from `agents/`.
- Global artifacts live under `agents/` and project-local artifacts live under `.agents/`.
- The global master file is `agents/AGENTS.global.md` and is only used for global artifacts.
- Artifact types are treated equally: `agents/`, `commands/`, and `skills/` are all published and distributed.
- Any `AGENTS.master.md` found in the project is inflated into an adjacent `AGENTS.md`.
- A `CLAUDE.md` companion is always created or replaced next to each `AGENTS.master.md` with a single line: `@./AGENTS.md`.
- Generated outputs under `dist/` are build artifacts. Do not edit them directly.
- Inline references are expanded for Claude, Codex, and Gemini outputs.
- Frontmatter is preserved by default; `hooks` are only emitted for Claude outputs.

## Rationale

- A single mother project prevents drift and split-brain artifact sources.
- Treating artifacts uniformly avoids cherry-picking and missing capabilities.
- Inflating master files keeps agent runtimes in sync while keeping source files stable.
- Limiting `hooks` to Claude matches current agent capabilities and avoids invalid configs.

## Scope

- Applies to all artifact generation and distribution in this repository.

## Enforcement

- Global publishing is gated to this repo only.
- Distribution runs validate artifacts per type before output.
- Generated files under `dist/` are overwritten on each distribution run.

## Exceptions

- None.
