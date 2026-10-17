---
description: Hand an open TeleClaude session to a different agent by replacing only its running agent CLI and supplying one classified continuation message.
---

# Agent Handoff — Spec

## What it is

Agent handoff replaces the running agent CLI inside one open TeleClaude session. The platform selects a successor, prepares its fresh launch completely, stops the predecessor, launches the successor on the session's existing managed execution surface, and supplies one platform-authored continuation message. The TeleClaude session remains the durable identity throughout.

Handoff is neither restart nor revival. It never creates, reopens, adopts, or repairs a session or host pane; the ordinary session-runtime owner decides whether the addressed open session is runnable. A closed session never enters handoff. A session whose execution surface is not currently available remains under its normal startup, restoration, or adoption flow and may be handed off only after that flow makes it runnable.

The swap changes only runtime ownership, the current native binding, runtime-start evidence, and the transcript chain. Session lifecycle, host-pane identity, adapter channels, lineage, relationships, reminders, listeners, direct links, and workflow ownership remain unchanged.

The predecessor transcript remains part of the session's continuity, and the successor receives one platform-classified continuation that identifies the predecessor and directs it to re-derive current state. This continuation is not human input and does not alter the session's last visible human input. Accepted input stays durable and ordered across the swap; terminal delivery waits until the successor and continuation are ready. Runtime ownership changes are serialized per session, and a failed swap leaves the session inspectable with its last truthful runtime binding.

## Canonical fields

### Use cases

#### UC-AH1: An open runnable session swaps agent CLIs in place

```gherkin
Given a person wants an open TeleClaude session to continue with a different supported agent
When the session's agent is handed off
Then the new agent continues on the same TeleClaude session
And the session's lifecycle and host-pane identity remain unchanged
```

#### UC-AH2: Session runnability remains outside handoff

#### UC-AH3: Selection reuses fresh-agent dispatch

#### UC-AH4: The native binding rotates without stale projection

#### UC-AH5: The successor receives one classified continuation

```gherkin
Given a person's open session is handed to a different agent
When the successor begins work
Then it receives the predecessor context as platform control and is directed to inspect the current working tree and re-derive state
And that continuation is not presented as human input
```

#### UC-AH6: Accepted input waits behind the swap boundary

#### UC-AH7: Concurrent runtime mutations do not overlap

#### UC-AH8: Completion and failure report actual progress

```gherkin
Given a handoff operation has been accepted after selecting its successor
When the operation completes or fails
Then the caller can inspect its truthful result naming the selected successor and the session's last truthful runtime state
```

#### UC-AH9: Remote handoff negotiates capability before dispatch

#### UC-AH10: Session-scoped relationships survive unchanged

### Cross-context references

- **integration** reports successor native identity and transcript metadata through the existing hook/outbox path; it never chooses the active agent.
- **reconciliation** advertises and checks the handoff feature through the shared capability map before point-to-point remote dispatch.
- **presentation** consumes ordinary session updates; it owns no handoff state or lifecycle rule.
- **workflow** continues to address the unchanged session id and is neither read nor mutated by handoff.

## Known caveats

- Handoff intentionally interrupts the predecessor process. It preserves durable session state and queued input, not an unfinished in-memory tool call.
- The successor starts a fresh native conversation and learns continuity from the classified handoff message and predecessor transcript; no native cross-provider resume exists.
- Missing execution surfaces remain the responsibility of ordinary startup, maintenance restoration, and explicit headless adoption. Handoff waits for their outcome rather than substituting for them.

## See Also

- docs/local/spec/feature/agent_runtime/agent-restart.md
- docs/local/spec/feature/agent_runtime/role-aware-agent-dispatch.md
- docs/local/spec/feature/agent_runtime/session-input-delivery.md
- docs/local/spec/feature/tui/session-actions.md
- docs/local/spec/message-headers.md
- docs/local/spec/feature/reconciliation/fleet-cross-version-interop.md
