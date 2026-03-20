# Requirements: refactor-agent-readiness

## Goal

Extract agent readiness detection out of daemon session orchestration into a dedicated readiness component with agent-owned metadata, clean layer boundaries, and event-driven lifecycle signaling. The settle-then-marker AND detection mechanism is proven and stays — this refactor relocates responsibility to respect layer ownership, boundary purity, and dependency inversion without changing the readiness contract.

## Scope

### In scope

- Moving readiness marker ownership from daemon session orchestration to agent metadata
- Creating a focused readiness detector that encapsulates pane-polling and readiness evaluation
- Emitting AGENT_READY and AGENT_READINESS_TIMEOUT events through the existing event bus
- Fixing the late-marker re-settle gap (marker found after initial settle must re-confirm stability)
- Making daemon session orchestration a consumer of the new detector instead of owning detection
- Updating existing tests to match the new boundary
- Adding focused tests for the extracted readiness detector

### Out of scope

- Changing the fundamental readiness detection algorithm (settle + marker AND logic stays)
- Direct TUI preview-pane implementation changes [inferred] — the input mentions preview timing as a downstream effect, but this todo does not require separate TUI work
- Adding new agent types or modifying agent CLI configurations
- Changing tmux pane capture mechanics

## Success Criteria

- [ ] SC-1: Readiness marker strings are no longer hardcoded in daemon session orchestration; agent metadata is the single source of truth
- [ ] SC-2: Readiness polling and marker-detection logic live in dedicated readiness-detection code rather than in daemon session orchestration
- [ ] SC-3: The daemon session message-injection path consumes readiness results and contains no direct polling or marker knowledge
- [ ] SC-4: When readiness succeeds, an AGENT_READY event is emitted through the event bus with the session ID
- [ ] SC-5: When readiness times out, an AGENT_READINESS_TIMEOUT event is emitted through the event bus with the session ID, the session is closed, and the user is notified of the failure
- [ ] SC-6: When a marker is found after the initial settle window, the readiness detector re-settles to confirm pane stability before reporting ready
- [ ] SC-7: Existing readiness-related tests are updated rather than deleted, and focused coverage is added for the extracted detector boundary
- [ ] SC-8: Pre-commit hooks pass (lint, type-check, tests)

## Constraints

- The readiness detector must be stateless — pure detection, no side effects beyond returning results. Event emission is the daemon's responsibility, not the detector's. [inferred]
- The detector must accept an agent identifier and resolve marker knowledge from agent metadata rather than hardcoding prompt markers in detection logic.
- Supporting helpers may stay with daemon session orchestration or move with readiness detection based on actual usage analysis; the extracted boundary must leave responsibility ownership explicit instead of split across both components. [inferred]
- New readiness event types must follow the established event system pattern and keep any documented event-bus lifecycle facts in sync. [inferred]

## Risks

- **Marker drift**: Agent CLI updates may change prompt markers. Centralizing markers in AgentName metadata makes updates single-site, reducing this risk versus the current scattered approach.
- **Re-settle timing**: The late-marker re-settle fix (SC-6) adds a second stability check. If the quiet window is too short, legitimate ready states may be delayed. The existing `quiet_s` parameter should govern this consistently.
