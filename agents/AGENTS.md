# Global agent artifacts configuration & distribution

This folder harbors agent artifact definitions and tooling to build and distribute artifacts to multiple AI agents (Claude Code, Codex, Gemini).

- ---

# Agent Artifact Distribution — Procedure

- ---

# Normalized Agent Artifacts — Concept

## What

Normalized agent artifacts are the shared, source‑of‑truth files we author to describe
agent behavior, their artifacts such as sub‑agents, commands, skills, and related configuration
in one consistent format.
They live in two scopes—global and project—so organization‑wide guidance and project‑specific
behavior can coexist without overwriting each other. These sources are intentionally
human‑authored and stable; the agent‑specific outputs are derived from them and treated
as build artifacts rather than hand‑edited files.

## Why

We normalize because we need a repeatable, maintainable way to keep multiple agent
runtimes aligned without copying the same intent into multiple formats. The problem is
that each runtime expects different file shapes and supports different features, which
creates drift and inconsistency when we author them separately. A normalized source
solves that by keeping the intent in one place and letting us emit only what each runtime
can actually use. That reduces duplication, prevents accidental divergence, and makes
changes safer: you update the source once and reliably regenerate every output.


## Goal

Build and distribute agent artifacts in this repository.

## Preconditions

- Global and/or project agent sources exist.

## Steps

1. Update the appropriate scope (global or project).
2. Run the distribution script to generate runtime-specific outputs.
3. Deploy generated outputs to local agent runtimes.

```
./scripts/distribute.py
./scripts/distribute.py --deploy
```

## Outputs

- Generated artifacts under `dist/`.
- Deployed artifacts under each agent runtime directory.

## Recovery

- If outputs are wrong, fix the source artifacts and rerun distribution.
- Do not edit generated files directly.

## See also

- docs/project/reference/agent-artifact-automation.md

- ---

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

