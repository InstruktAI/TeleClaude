---
description: 'Steps to build and distribute agent artifacts in this repository.'
id: 'project/procedure/agent-artifact-distribution'
scope: 'project'
type: 'procedure'
---

# Agent Artifact Distribution — Procedure

## Required reads

- @~/.teleclaude/docs/general/concept/normalized-agent-artifacts.md

## Goal

Build and distribute agent artifacts in this repository.

## Preconditions

- Global and/or project agent sources exist.

## Steps

1. Update the appropriate scope (global or project).
2. Run `telec sync` to generate and deploy runtime-specific outputs.

## Outputs

- Generated artifacts under `dist/`.
- Deployed artifacts under each agent runtime directory.

## Recovery

- If outputs are wrong, fix the source artifacts and rerun distribution.
- Do not edit generated files directly.

## See also

- docs/project/spec/agent-artifact-automation.md
