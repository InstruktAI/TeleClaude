---
id: teleclaude/policy/adapter-boundaries
type: policy
scope: project
description: Adapter boundaries and transport metadata must not drive domain intent.
requires:
  - ../concept/adapter-types.md
---

Policy
- Core logic never interprets adapter-specific payloads as domain intent.
- Transport metadata (computer names, adapter types) is not used to decide business logic.
- AdapterClient is the only gateway for adapter operations.
