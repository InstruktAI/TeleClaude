---
description:
  UI adapters translate human inputs into events and render outputs with
  UX rules.
id: teleclaude/architecture/ui-adapter
scope: project
type: architecture
---

## Required reads

- @teleclaude/concept/adapter-types
- @teleclaude/architecture/ux-message-cleanup

Responsibilities

- Normalize user commands and messages into daemon events.
- Render session output and feedback according to UX cleanup rules.
- Manage topics or channels for per-session organization.
- Preserve session affinity (route feedback back to the last input origin).

Boundaries

- No cross-computer orchestration responsibilities.
- No domain policy decisions; UI is translation and presentation only.

Invariants

- UI adapters do not mutate core state directly.
- Cleanup rules are enforced consistently for each session.
