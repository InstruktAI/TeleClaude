---
id: teleclaude/architecture/context-selection
type: architecture
scope: project
description: Context selection pipeline that picks relevant snippets for MCP get_context.
requires:
  - context-index.md
---

Purpose
- Select relevant documentation snippets for a given request.

Inputs/Outputs
- Inputs: user corpus and snippet metadata (id, description, type, scope).
- Outputs: ordered snippet list with resolved requires dependencies.

Primary flows
- Build snippet metadata from docs/snippets and global snippets.
- Call the local LLM selector to choose snippet IDs.
- Resolve requires dependencies and order by scope priority (global -> domain -> project).
- Persist selected IDs per session to avoid repeated context churn.

Failure modes
- If selection fails, returns an empty snippet list rather than partial output.
