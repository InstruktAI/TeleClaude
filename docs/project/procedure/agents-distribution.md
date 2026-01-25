---
description: Steps to build and distribute agent artifacts in this repository.
id: docs/procedure/agents-distribution
scope: project
type: procedure
---

# Agents Distribution — Procedure

## Goal

## Required reads

- @~/.teleclaude/docs/software-development/concept/agent-artifact-distribution.md
- @~/.teleclaude/docs/software-development/guide/agent-artifacts-quickstart.md

Build and distribute agent artifacts in this repository.

## Preconditions

- Source artifacts exist in `commands/`, `skills/`, and `AGENTS.master.md`.

## Steps

1. Author or update source artifacts in `commands/`, `skills/`, and `AGENTS.master.md`.
2. Run the local distribution script to generate runtime-specific outputs.
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
