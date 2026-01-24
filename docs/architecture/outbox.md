---
description: Durable outbox table for agent hook events.
id: teleclaude/architecture/outbox
scope: project
type: architecture
---

## Required reads

- @teleclaude/architecture/database
- @teleclaude/reference/event-types

## Purpose

- Provide durable delivery semantics for agent hook events.

## Inputs/Outputs

- Inputs: hook events from agent hook receivers.
- Outputs: outbox rows consumed by daemon processors.

## Components

- hook_outbox: stores agent hook events until consumed by the daemon.

## Primary flows

- Hook receiver inserts rows with normalized payloads.
- Daemon locks, processes, and marks rows as delivered.

## Invariants

- Outbox rows remain until marked delivered.
- Hook receiver always writes to hook_outbox instead of invoking daemon directly.

## Failure modes

- Stuck rows indicate a processing failure or consumer outage.
