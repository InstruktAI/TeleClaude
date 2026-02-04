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

1. Choose the artifact type (agent, skill, command, or AGENTS.md).
2. Follow the corresponding schema and taxonomy requirements.
3. Ensure frontmatter fields are complete and consistent (except AGENTS.md, which has none).
4. Add the artifact title (`# ...`) for all artifacts.
5. Apply the artifact-specific rules below.
6. Run `telec sync --warn-only` to validate and rebuild artifacts.

## Artifact-specific rules

| Artifact | Required placement rules |
| --- | --- |
| **Command** | Add the activation line immediately after the title. If needed, place `## Required reads` immediately after the activation line. |
| **Agent** | Add the activation line immediately after the title. If needed, place `## Required reads` immediately after the activation line. |
| **Skill** | If needed, place `## Required reads` immediately after the title. |
| **AGENTS.md** | No frontmatter. Must live at repo root. If needed, place `## Required reads` immediately after the title. Keep content minimal and role‑specific. |

## Outputs

- Updated artifact files in the selected scope.
- Updated generated artifacts in tool-specific output folders.

## Recovery

- If validation fails, fix the schema issues and rebuild.
