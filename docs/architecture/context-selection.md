---
description: Context selection pipeline that picks relevant docs for MCP get_context.
id: teleclaude/architecture/context-selection
scope: project
type: architecture
---

# Context Selection — Architecture

## Purpose

- @docs/architecture/context-index

- Select relevant documentation docs for a given request.

- Inputs: optional areas filter and snippet metadata (id, description, type, scope).
- Outputs: ordered snippet list with resolved requires dependencies.

- Selected IDs must exist in the snippet index.
- Requires dependencies are always expanded before output.

- Build snippet metadata from docs and global docs.
- Return a filtered index (frontmatter only) when no IDs are provided.
- Accept selected snippet IDs from the caller and resolve requires dependencies.
- Order by scope priority (global -> domain -> project).
- Persist selected IDs per session to avoid repeated context churn.

- If no valid snippet IDs are provided, returns an empty snippet list.

- TBD.

- TBD.

- TBD.

- TBD.

## Inputs/Outputs

- TBD.

## Invariants

- TBD.

## Primary flows

- TBD.

## Failure modes

- TBD.
