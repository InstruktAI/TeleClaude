---
id: general/concept/normalized-agent-artifacts
type: concept
scope: global
description: Normalized agent artifact primitives and how they map to supported CLIs.
---

# Normalized Agent Artifacts — Concept

## Purpose

Define the single source of truth for agent configuration so we can generate
compatible files for Claude, Codex, and Gemini without duplicating work.

## Inputs/Outputs

- **Inputs**: normalized sources in two scopes:
  - **Global scope**: `TeleClaude/agents/` (global agents, commands, skills).
  - **Project scope**: `<project>/.agents/` (project agents, commands, skills).
- **Outputs**: generated CLI files under `dist/claude/*`, `dist/codex/*`, `dist/gemini/*`.

## Invariants

- Global and project scopes are separate; each has its own sources.
- Normalized sources are the only editable source of truth.
- Generated outputs are never edited manually.
- CLI-specific features that do not fit the shared schema live in CLI overlays.

## Primary flows

1. Edit normalized sources in the appropriate scope (global or project).
2. Run the distribution script to generate runtime outputs.
3. Use generated outputs in each CLI.

## Failure Modes

- Outputs drift when distribution is skipped.
- CLI-specific fields leak into normalized sources and break other runtimes.

## See also

- docs/general/reference/agent-artifacts
- docs/project/procedure/agent-artifact-distribution
