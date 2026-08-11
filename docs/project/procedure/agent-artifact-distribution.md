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

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

2. Run `telec sync` to generate and deploy runtime-specific outputs.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

2. Run `telec sync` to validate the sources. Runtime-specific outputs are
   generated and published once source activity settles.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

## Outputs

- Generated artifacts under `dist/`.
- Deployed artifacts under each agent runtime directory.

## Recovery

- If outputs are wrong, fix the source artifacts and rerun distribution.
- Do not edit generated files directly.

## See Also

- docs/project/spec/agent-artifact-automation.md
