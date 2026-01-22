---
description:
  UI adapters translate human inputs into events and render outputs with
  UX rules.
id: teleclaude/architecture/ui-adapter
requires:
  - teleclaude/concept/adapter-types
  - teleclaude/architecture/ux-message-cleanup
scope: project
type: architecture
---

Responsibilities

- Normalize user commands and messages into daemon events.
- Render session output and feedback according to UX cleanup rules.
- Manage topics or channels for per-session organization.

Boundaries

- No cross-computer orchestration responsibilities.
