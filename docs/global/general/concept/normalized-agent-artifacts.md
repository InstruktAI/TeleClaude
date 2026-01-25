---
id: general/concept/normalized-agent-artifacts
type: concept
scope: global
description: Normalized agent artifact primitives and how they map to supported CLIs.
---

# Normalized Agent Artifacts — Concept

## Purpose

Define the median, tool-agnostic artifact set that serves as the single source of truth for
Claude Code, Gemini CLI, and Codex CLI integrations.

## Inputs/Outputs

**Inputs (source of truth):**

- **Agents**: `AGENTS.master.md`
- **Commands**: `agents/commands/*.md`
- **Skills**: `agents/skills/*/SKILL.md`

**Outputs (generated):**

- `dist/claude/*`
- `dist/gemini/*`
- `dist/codex/*`

## Primary flows

1. Author normalized artifacts under `agents/`.
2. Run distribution to generate CLI-specific outputs.
3. Consume generated outputs in each CLI.

## Invariants

- The normalized primitives are the single source of truth.
- Generated outputs are derived and must be regenerated on change.
- CLI-specific capabilities that do not fit the median schema must live in adapter-specific
  overlays, not in the normalized sources.

## Failure modes

- Artifacts drift when distribution is skipped.
- CLI-specific fields leak into normalized sources and break other runtimes.
