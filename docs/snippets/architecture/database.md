---
id: teleclaude/architecture/database
type: architecture
scope: project
description: SQLite persistence for sessions, outboxes, UX state, and agent metadata.
requires: []
---

Purpose
- Persist daemon state for sessions, command durability, and UX continuity.

Stored data
- Sessions and their metadata (title, status, agent info, tmux name).
- Outbox tables for API commands and hook events.
- UX state for message cleanup and registry message IDs.
- Agent assignments and voice mappings.

Invariants
- The daemon uses a single SQLite file at teleclaude.db in the project root.
- Schema migrations run on startup to keep tables current.
