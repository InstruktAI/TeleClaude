---
description: Durable outbox table for agent hook events.
id: teleclaude/architecture/outbox
scope: project
type: architecture
---

# Outbox — Architecture

## Purpose

- @docs/architecture/database
- @docs/reference/event-types

- Provide durable delivery semantics for agent hook events.

- Inputs: hook events from agent hook receivers.
- Outputs: outbox rows consumed by daemon processors.

- hook_outbox: stores agent hook events until consumed by the daemon.

- Hook receiver inserts rows with normalized payloads.
- Daemon locks, processes, and marks rows as delivered.

- Outbox rows remain until marked delivered.
- Hook receiver always writes to hook_outbox instead of invoking daemon directly.

- Stuck rows indicate a processing failure or consumer outage.

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
