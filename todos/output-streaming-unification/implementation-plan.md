# Implementation Plan: Output Streaming Unification

## Objective

Refactor outbound architecture into a clean two-channel model:

- state snapshots via cache/API websocket,
- agent activity stream via AdapterClient/distributor.

## Phase 1: Contracts and boundaries

### 1. Define canonical activity event model

- Add/confirm typed internal events:
  - `user_prompt_submit`
  - `agent_output_update`
  - `agent_output_stop`
- Include minimum routing metadata:
  - `session_id`
  - event timestamp
  - producer source (hook/poller)
  - activity payload

### 2. Document boundary responsibilities

- AgentCoordinator:
  - orchestrates agent lifecycle activity,
  - emits activity events and session updates,
  - no adapter-specific formatting.
- AdapterClient/OutputDistributor:
  - routing, fan-out, failure isolation.
- Adapters:
  - protocol translation only.

## Phase 2: Distribution plumbing

### 3. Add output distributor abstraction (if not already explicit)

- Keep it inside AdapterClient if practical.
- Ensure per-consumer async queue isolation.
- Add backpressure behavior:
  - coalesce/drop policy for high-frequency `agent_output_update`.

### 4. Introduce stream gateway adapter

- Output-only UI adapter implementation.
- Provides shared stream transport boundary for TUI and Web consumers.
- Supports consumer registration and per-session stream subscriptions.

### 5. Route canonical activity events through distributor

- Poller/hook/coordinator publish canonical activity events.
- Distributor fans out by routing metadata/origin policy.

## Phase 3: Consumer integration

### 6. TUI stream consumer integration

- Add TUI consumer path for rich output streaming from stream gateway.
- Keep API websocket for state model updates (session list/status/highlights metadata).

### 7. Web stream consumer integration

- Define web adapter consumption path:
  - websocket native consumption, and/or
  - SSE translation for AI SDK format.
- Keep translation at adapter boundary.

## Phase 4: Migration safety and observability

### 8. Incremental rollout

- Feature-flag stream path per consumer if needed.
- Start with internal/TUI consumer, then add web consumer.

### 9. Instrumentation

- Metrics/logs:
  - consumer queue depth
  - drop/coalesce counts
  - publish latency
  - disconnect/reconnect events

### 10. Verification

- Contract tests for canonical activity events.
- Integration tests:
  - one producer -> multiple consumers.
  - slow consumer does not block fast consumers.
  - Telegram unaffected during transition.
  - TUI receives stream activity without relying on cache for chunk delivery.

## Files expected to change

- `teleclaude/core/agent_coordinator.py` (boundary cleanup only)
- `teleclaude/core/adapter_client.py` (distributor/fan-out wiring)
- `teleclaude/adapters/` (stream gateway + consumers)
- `teleclaude/api_server.py` (state channel remains snapshot-focused)
- `docs/project/design/architecture/*.md` (target-state architecture updates)

## Risks

1. Hidden coupling between cache updates and current TUI behavior.
2. Event duplication during transition if both old and new paths run simultaneously.
3. Queue policy too aggressive or too loose can hurt UX or memory.

## Exit criteria

1. Outbound architecture follows target design doc.
2. TUI and Web stream consumers are aligned on the same canonical activity contract.
3. State and streaming paths are clearly separated in code and docs.
