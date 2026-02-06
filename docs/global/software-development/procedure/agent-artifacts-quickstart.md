---
id: 'software-development/procedure/agent-artifacts-quickstart'
type: 'procedure'
scope: 'domain'
description: 'Quickstart for authoring and distributing agent artifacts.'
---

# Agent Artifacts Quickstart — Procedure

## Goal

Get an agent artifact authored and distributed to tool-specific outputs.

## Preconditions

- Access to the target repository and artifact scopes.
- Artifact schema references available.

## Steps

1. Choose the scope (global or project) for the artifact.
2. Author or update the artifact in the chosen scope following the schema.
3. Validate snippet structure and required reads.
4. Run `telec sync` to generate and deploy outputs.

## Outputs

- Authored artifact in the chosen scope.
- Generated tool-specific outputs after `telec sync`.

## Recovery

- Editing generated output files directly — they get overwritten on next distribution run.
- Forgetting to run distribution after changing source artifacts — runtimes will use stale outputs.
