---
id: teleclaude/architecture/database
type: architecture
scope: project
description: SQLite persistence for sessions, hook outbox, UX state, and agent metadata.
---

# Database — Architecture

## Purpose

- Persist daemon state for sessions, command durability, and UX continuity.

- Inputs: session events, command queue entries, UX state updates, hook outbox events.
- Outputs: persisted records for recovery and cache rebuilds.

- Write sessions and command metadata on creation and updates.
- Append hook outbox events for durable delivery.
- Persist UX cleanup state for message deletion.

- Sessions and their metadata (title, status, agent info, tmux name).
- Hook outbox rows for agent events.
- UX state for message cleanup and registry message IDs.
- Agent assignments and voice mappings.

- The daemon uses a single SQLite file at teleclaude.db in the project root.
- Schema migrations run on startup to keep tables current.

- Corrupt database prevents recovery of sessions and UX state.

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
