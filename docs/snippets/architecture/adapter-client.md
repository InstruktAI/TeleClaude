---
description: AdapterClient centralizes adapter lifecycle, UI/transport routing, and
  cross-computer requests.
id: teleclaude/architecture/adapter-client
requires:
- teleclaude/concept/adapter-types
scope: project
type: architecture
---

Purpose
- Centralize adapter lifecycle, UI/transport routing, and cross-computer requests.

Inputs/Outputs
- Inputs: direct calls from command handlers and daemon orchestration logic.
- Outputs: UI broadcasts, transport requests, and adapter-side lifecycle operations.

Primary flows
- Broadcasts output updates to the origin UI adapter plus other UI adapters.
- Routes remote requests to the first transport adapter implementing RemoteExecutionProtocol.
- Manages UI cleanup hooks (pre/post handlers) and observer broadcasts for user commands.

Invariants
- Only successfully started adapters are registered.
- Transport adapters are not used for UI broadcast.
- AdapterClient is the single routing point for adapter operations.

Failure modes
- Missing transport adapter raises a runtime error for remote requests.
- UI adapter failures are logged; origin adapter failures are treated as fatal for the operation.