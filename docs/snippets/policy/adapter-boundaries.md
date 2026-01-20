---
id: policy/adapter-boundaries
type: policy
scope: project
description: Strict separation between UI/Transport adapters and core logic.
---

# Adapter Boundary Policy

## Purpose
Ensures that the core domain logic remains platform-agnostic and easy to test, while adapters handle the messiness of external APIs.

## Rules
1. **Normalization**: Adapters MUST normalize external inputs into `Command` objects before passing them to the core.
2. **No Core Leakage**: Adapter-specific types (e.g., Telegram's `Update`, Redis's raw stream data) MUST NOT enter the core.
3. **Protocols**: All adapter-core interactions MUST happen via established Python Protocols (e.g., `RemoteExecutionProtocol`, `UiAdapter`).
4. **Origin-Only Feedback**: User feedback (clutter cleanup) is only performed by the adapter that originated the request.

## Result
A clean "onion" architecture where the core knows nothing about Telegram or Redis.