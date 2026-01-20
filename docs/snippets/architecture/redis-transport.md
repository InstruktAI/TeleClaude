---
id: architecture/redis-transport
description: Redis Streams transport for cross-computer AI-to-AI messaging and session output delivery.
type: architecture
scope: project
requires:
  - adapter-client.md
  - cache.md
  - event-model.md
---

# Redis Transport

## Purpose
- Enable reliable cross-computer messaging and output streaming using Redis Streams.

## Inputs/Outputs
- Inputs: inbound Redis streams (`messages:{computer}`) and registry heartbeat keys.
- Outputs: outbound streams (`output:{session_id}`), peer registry, cache updates.

## Invariants
- Each computer polls its own `messages:{computer_name}` stream for commands.
- Each session has an output stream named `output:{session_id}` for remote consumers.
- Heartbeats use TTL-based keys to advertise online status.

## Primary Flows
- Start: connect to Redis and launch poll loops for messages, heartbeats, and peer refresh.
- Receive: parse inbound command strings and emit TeleClaude events via AdapterClient.
- Respond: publish command results and output updates to the appropriate Redis stream.

## Failure Modes
- Connection failures trigger retry loops and log throttling for idle polling.
- Invalid payloads are rejected with error logs; polling continues.
