# Agents Repo Workflow (Local)

Required reads

@~/.teleclaude/docs/baseline/procedure/agent-artifact-authoring.md
@/Users/Morriz/Documents/Workspace/InstruktAI/TeleClaude/docs/procedure/agents-distribution.md

## Goal

Maintain agent artifacts and keep generated outputs in sync.

## Steps

1. Edit source artifacts only (`AGENTS.master.md`, `commands/`, `skills/`).
2. Run distribution to regenerate outputs.
3. Validate outputs by spot-checking generated files.

## Recovery

- If generated outputs drift, rerun distribution from source artifacts.
