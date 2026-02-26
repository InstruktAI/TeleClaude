---
id: 'general/policy/context-retrieval'
type: 'policy'
scope: 'global'
visibility: 'public'
description: 'Guidelines for AI agents to retrieve relevant documentation snippets on demand.'
---

# Context Retrieval Policy — Policy

## Rules

- Use `telec docs index` as the default entry point for information discovery.
- Call `telec docs index` before any task where missing context could alter decisions.
- Use the two‑phase flow: index first, then selected snippet IDs.

## Rationale

- Immediate context prevents drift from established policy, architecture, and procedure.

## Scope

- Applies to all agents, all projects, and all tasks.

## Enforcement

- If unsure about policies, procedures, roles, or constraints, run `telec docs index` before editing or executing.

## Exceptions

- None.
