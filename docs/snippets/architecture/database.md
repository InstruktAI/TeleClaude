---
id: architecture/database
description: SQLite persistence for sessions, outboxes, UX state, and agent availability.
type: architecture
scope: project
requires: []
---

# Database

## Purpose
- Persist sessions, message cleanup state, and outbox delivery for hooks/API.

## Inputs/Outputs
- Inputs: database path from config or `TELECLAUDE_DB_PATH` override; schema + migrations.
- Outputs: async session store, outbox queues, and UX/system settings.

## Invariants
- SQLite is configured with WAL mode, NORMAL synchronous, and busy_timeout.
- Tables include: sessions, pending_message_deletions, hook_outbox, api_outbox, system_settings,
  agent_availability, voice_assignments.
- In-memory database mode uses a temporary file for runtime compatibility.
- Adapter metadata is normalized on startup (e.g., numeric topic IDs).

## Primary Flows
- Initialize: create schema, run migrations, create async engine.
- CRUD: create/update/close sessions; enqueue/dequeue outbox rows; track pending deletions.

## Failure Modes
- JSON parsing errors in adapter metadata are skipped; normalization is best-effort.
- Operational errors in legacy tables are logged and bypassed.
