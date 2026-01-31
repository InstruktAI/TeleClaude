# Context Retrieval Policy — Policy

## Rules

- Use `teleclaude__get_context` as the default entry point for information discovery.
- Call `teleclaude__get_context` before any task where missing context could alter decisions.
- Use the two‑phase flow: index first, then selected snippet IDs.

## Rationale

- Immediate context prevents drift from established policy, architecture, and procedure.

## Scope

- Applies to all agents, all projects, and all tasks.

## Enforcement

- If unsure about policies, procedures, roles, or constraints, call get_context before editing or executing.

## Exceptions

- None.
