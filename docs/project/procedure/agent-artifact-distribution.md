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

<!-- planned-change:retire-docs-watcher -->
2. The docs watcher publishes the change; runtime-specific outputs regenerate on save.
<!-- change:retire-docs-watcher -->
2. Commit the change; commit or merge maintenance publishes the recorded range and runtime-specific outputs regenerate.
<!-- /planned-change:retire-docs-watcher -->

## Outputs

- Generated artifacts under `dist/`.
- Deployed artifacts under each agent runtime directory.

## Recovery

- If outputs are wrong, fix the source artifacts and rerun distribution.
- Do not edit generated files directly.

## See Also

- docs/project/spec/agent-artifact-automation.md
