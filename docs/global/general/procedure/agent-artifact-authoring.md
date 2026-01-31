---
id: general/procedure/agent-artifact-authoring
type: procedure
scope: global
description: Author agent artifacts (agents, skills, commands) that compile into tool-specific formats.
---

# Agent Artifact Authoring — Procedure

## Goal

Create or update agent artifacts that follow the schema and compile correctly for supported CLIs.

## Preconditions

- Artifact schema references are available.
- Target repository includes global or project artifact scopes.

## Steps

1. Choose the artifact type (agent, skill, command).
2. Follow the corresponding schema and taxonomy requirements.
3. Ensure frontmatter fields are complete and consistent.
4. Add required reads at the very top of the body, before any headings.
5. Order required reads from general to concrete: concept → principle → policy → role → procedure → reference.
6. Add the artifact title (`# ...`). For commands and agents only, add a one-line role activation statement immediately after the title.
7. Use required reads for hard dependencies.
8. Run the repository tooling that validates and builds artifacts.

## Outputs

- Updated artifact files in the selected scope.
- Updated generated artifacts in tool-specific output folders.

## Recovery

- If validation fails, fix the schema issues and rebuild.
