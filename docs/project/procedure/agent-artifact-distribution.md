---
description: Steps to build and distribute agent artifacts in this repository.
id: docs/procedure/agent-artifact-distribution
scope: project
type: procedure
---

# Agent Artifact Distribution — Procedure

## Goal

## Required reads

- @docs/general/concept/normalized-agent-artifacts

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
