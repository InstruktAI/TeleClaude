---
id: teleclaude/architecture/database
type: architecture
scope: project
description: SQLite persistence for sessions, hook outbox, UX state, and agent metadata.
requires: []
---

## Purpose

- Persist daemon state for sessions, command durability, and UX continuity.

## Inputs/Outputs

- Inputs: session events, command queue entries, UX state updates, hook outbox events.
- Outputs: persisted records for recovery and cache rebuilds.

## Primary flows

- Write sessions and command metadata on creation and updates.
- Append hook outbox events for durable delivery.
- Persist UX cleanup state for message deletion.

## Stored data

- Sessions and their metadata (title, status, agent info, tmux name).
- Hook outbox rows for agent events.
- UX state for message cleanup and registry message IDs.
- Agent assignments and voice mappings.

## Invariants

- The daemon uses a single SQLite file at teleclaude.db in the project root.
- Schema migrations run on startup to keep tables current.

## Failure modes

- Corrupt database prevents recovery of sessions and UX state.
