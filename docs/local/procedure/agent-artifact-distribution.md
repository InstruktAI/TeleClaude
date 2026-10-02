---
description: 'Steps to build and distribute agent artifacts in this repository.'
visibility: 'public'
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

2. Commit the change; commit or merge maintenance publishes the recorded range and runtime-specific outputs regenerate.

## Outputs

- Generated artifacts under `dist/`.
- Deployed artifacts under each agent runtime directory.

## Recovery

- If outputs are wrong, fix the source artifacts and commit the fix.
- If committed sources did not reach the deployed outputs, run `telec sync` from
  the project's home directory.
- Do not edit generated files directly.

## See Also

- docs/local/spec/agent-artifact-automation.md
