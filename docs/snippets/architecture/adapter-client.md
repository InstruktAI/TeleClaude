---
id: teleclaude/architecture/adapter-client
type: architecture
scope: project
description: AdapterClient centralizes adapter lifecycle, event routing, and cross-computer requests.
requires:
  - ../concept/adapter-types.md
  - ../reference/event-types.md
---

Purpose
- Centralize adapter lifecycle, event routing, and cross-computer requests.

Inputs/Outputs
- Inputs: adapter events (lifecycle, agent events, errors, voice/file, system commands).
- Outputs: UI broadcasts, transport requests, and event dispatch to daemon handlers.

Primary flows
- Emits events through an internal event bus; daemon subscribes via client.on.
- Broadcasts output updates to the origin UI adapter plus other UI adapters.
- Routes remote requests to the first transport adapter implementing RemoteExecutionProtocol.

Invariants
- Only successfully started adapters are registered.
- Transport adapters are not used for UI broadcast.
- AdapterClient is the single routing point for adapter operations.

Failure modes
- Missing transport adapter raises a runtime error for remote requests.
- UI adapter failures are logged; origin adapter failures are treated as fatal for the operation.
