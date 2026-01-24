# Agent Artifact Distribution

Required reads

@~/.teleclaude/docs/baseline/reference/agent-artifacts.md

## Purpose

Explain the global model for how agent artifacts are authored once and distributed
into agent-specific formats.

## Inputs / Outputs

- Inputs: `agents/`, `skills/`, `commands/` authored in a repo.
- Outputs: agent-specific artifact bundles generated for supported runtimes.

## Invariants

- Source artifacts remain the single source of truth.
- Generated artifacts are derived outputs and should not be edited directly.
- Distribution preserves intent while adapting syntax for each agent runtime.

## Primary flow

1. Author artifacts in the canonical folders.
2. A watcher or build step converts them into runtime-specific formats.
3. Generated outputs are placed into each agent runtime's expected location.

## Failure modes

- Missing or vague metadata reduces discoverability.
- Editing generated artifacts causes drift and is overwritten by the next build.
