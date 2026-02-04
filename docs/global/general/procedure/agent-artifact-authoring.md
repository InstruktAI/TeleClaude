---
id: general/procedure/agent-artifact-authoring
type: procedure
scope: global
description: Author agent artifacts (agents, skills, commands) that compile into tool-specific formats.
---

# Agent Artifact Authoring — Procedure

## Required reads

- @~/.teleclaude/docs/general/spec/snippet-authoring-schema.md

## Goal

Create or update agent artifacts that follow the schema and compile correctly for supported CLIs.

## Preconditions

- Artifact schema references are available.
- Target repository includes global or project artifact scopes.

## Steps

1. Choose the artifact type (agent, skill, command, or AGENTS.md).
2. Follow the corresponding schema and taxonomy requirements.
3. Ensure frontmatter fields are complete and consistent (except AGENTS.md, which has none).
4. Add the artifact title (`# ...`) for all artifacts.
5. Apply the artifact-specific rules below.
6. After any doc change, run `telec sync`.

## Outputs

- Updated artifact files in the selected scope.
- Updated generated artifacts in tool-specific output folders.

## Recovery

- If `telec sync` fails, fix the issue and rerun it.
