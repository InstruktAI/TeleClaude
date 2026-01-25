# Agents Distribution (Local)

Required reads

@~/.teleclaude/docs/baseline/procedure/agent-artifact-authoring.md
@~/.teleclaude/docs/software-development/concept/agent-artifact-distribution.md
@~/.teleclaude/docs/software-development/guide/agent-artifacts-quickstart.md

## Goal

Build and distribute agent artifacts in this repository.

## Steps

1. Author or update source artifacts in `commands/`, `skills/`, and `AGENTS.master.md`.
2. Run the local distribution script to generate runtime-specific outputs.
3. Deploy generated outputs to local agent runtimes.

## Commands

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
