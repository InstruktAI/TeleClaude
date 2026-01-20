---
id: teleclaude/role/ui-adapter
type: role
scope: project
description: UI adapters translate human inputs into events and render outputs with UX rules.
requires:
  - ../concept/adapter-types.md
  - ../architecture/ux-message-cleanup.md
---

Responsibilities
- Normalize user commands and messages into daemon events.
- Render session output and feedback according to UX cleanup rules.
- Manage topics or channels for per-session organization.

Boundaries
- No cross-computer orchestration responsibilities.
