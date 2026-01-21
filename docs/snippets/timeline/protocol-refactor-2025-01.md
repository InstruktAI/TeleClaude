---
id: timeline/protocol-refactor-2025-01
type: timeline
scope: project
description: Major architectural refactor moving to Protocol-based adapters and Redis transport.
---

# Timeline: Protocol & Transport Refactor (Jan 2025)

## 2025-01-05: Inception

- Identified limitations in direct Telegram-only multi-computer support.
- Proposed Redis-based transport for sub-second AI-to-AI communication.

## 2025-01-08: Core Abstraction

- Introduced `RemoteExecutionProtocol` and `UiAdapter` protocols.
- Decoupled `CommandService` from the Telegram API.

## 2025-01-12: Redis Implementation

- Shipped `RedisTransport` with heartbeat-based computer discovery.
- Implemented `teleclaude__list_computers` MCP tool.

## 2025-01-15: Outbox Hardening

- Added `hook_outbox` for resilient agent event capture.
- Standardized `caller_session_id` injection in `mcp-wrapper`.

## 2025-01-20: Snippet Unification (Current)

- Standardized AI context via `docs/snippets/` to improve agent performance.
