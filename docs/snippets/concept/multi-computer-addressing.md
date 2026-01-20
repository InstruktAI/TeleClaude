---
id: concept/multi-computer-addressing
type: concept
scope: global
description: How computers and sessions are addressed in a distributed TeleClaude network.
---

# Multi-Computer Addressing

## Concepts
1. **Computer Shorthand**: Every installation has a unique `computer_name` (e.g., `macbook`, `raspi`).
2. **Global Addressing**: Sessions can be addressed using `(computer, session_id)`.
3. **Discovery**: Computers broadcast heartbeats via Redis (if enabled); the `ComputerRegistry` tracks online status and capabilities.

## Transports
- **Local**: `computer="local"` bypasses the network for direct daemon interaction.
- **Remote**: Any other name triggers the `RedisTransport` to route commands to the target computer.

## Identity
- `session_id`: Global UUID for the TeleClaude session.
- `native_session_id`: ID assigned by the agent environment (e.g., Claude Code's internal ID), mapped to `session_id` in the `hook_outbox`.
