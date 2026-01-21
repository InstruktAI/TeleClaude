---
description: Context selection pipeline that picks relevant snippets for MCP get_context.
id: teleclaude/architecture/context-selection
requires:
  - teleclaude/architecture/context-index
scope: project
type: architecture
---

## Purpose

- Select relevant documentation snippets for a given request.

## Inputs/Outputs

- Inputs: user corpus and snippet metadata (id, description, type, scope).
- Outputs: ordered snippet list with resolved requires dependencies.

## Invariants

- Selected IDs must exist in the snippet index.
- Requires dependencies are always expanded before output.

## Primary flows

- Build snippet metadata from docs/snippets and global snippets.
- Return a filtered index (frontmatter only) when no IDs are provided.
- Accept selected snippet IDs from the caller and resolve requires dependencies.
- Order by scope priority (global -> domain -> project).
- Persist selected IDs per session to avoid repeated context churn.

## Failure modes

- If no valid snippet IDs are provided, returns an empty snippet list.
