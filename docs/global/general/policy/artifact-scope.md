---
id: 'general/policy/artifact-scope'
type: 'policy'
scope: 'global'
description: 'Determine whether an artifact belongs in global or project scope before creating it.'
---

# Artifact Scope — Policy

## Rules

- Every authored artifact — doc snippet, skill, command, or agent — must have its scope determined before creation.
- **Global** (`docs/global/`, `agents/`): the knowledge or tooling applies across all projects. Examples: general procedures, cross-project policies, shared CLI tooling.
- **Project** (`docs/project/`, `.agents/`): the knowledge or tooling is specific to this repository. Examples: project architecture, repo-specific workflows, local commands.
- Scope must not be inferred or assumed. Apply these criteria:
  1. Does this artifact reference project-specific code, architecture, or configuration? → Project.
  2. Would this artifact be useful in a different repository with no changes? → Global.
  3. If neither criterion gives a clear answer, ask the requester before proceeding.
- When redirecting from one authoring procedure to another (e.g., skill gate redirects to doc snippet), the scope question carries over — it must still be answered.

## Rationale

- Agents default to guessing scope when it is not explicit, leading to project-specific knowledge polluting the global namespace or global knowledge trapped in a single repo.
- A single shared policy prevents each authoring procedure from duplicating scope logic.

## Scope

- Applies to all authoring procedures: doc-snippet-authoring, skill-authoring, agent-artifact-authoring, and any future authoring flows.

## Enforcement

- Authoring procedures must include this policy as a Required read.
- An artifact created in the wrong scope is a defect — move it and update references.

## Exceptions

- None.
