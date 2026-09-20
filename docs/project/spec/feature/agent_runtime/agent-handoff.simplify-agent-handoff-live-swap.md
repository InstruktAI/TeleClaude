---
description: Hand an open TeleClaude session to a different agent by replacing only its running agent CLI and supplying one classified continuation message.
---

# Agent Handoff — Spec

## What it is

Agent handoff replaces the running agent CLI inside one open TeleClaude session. The platform selects a successor, prepares its fresh launch completely, stops the predecessor, launches the successor on the session's existing managed execution surface, and supplies one platform-authored continuation message. The TeleClaude session remains the durable identity throughout.

Handoff is neither restart nor revival. It never creates, reopens, adopts, or repairs a session or host pane; the ordinary session-runtime owner decides whether the addressed open session is runnable. A closed session never enters handoff. A session whose execution surface is not currently available remains under its normal startup, restoration, or adoption flow and may be handed off only after that flow makes it runnable.

The swap changes only runtime ownership, the current native binding, runtime-start evidence, and the transcript chain. Session lifecycle, host-pane identity, adapter channels, lineage, relationships, reminders, listeners, direct links, and workflow ownership remain unchanged.

## Canonical fields

### Use cases

#### UC-AH1: An open runnable session swaps agent CLIs in place

```gherkin
Given an open TeleClaude session has a running agent on a managed execution surface
When an authorized caller requests handoff
Then the platform selects and fully prepares a fresh successor launch before terminating the predecessor
And the predecessor agent process exits before the successor is launched
And the successor is launched on the same managed execution surface
And the TeleClaude session id, lifecycle status, closed marker, host-pane identity, and adapter channels do not change
```

#### UC-AH2: Session runnability remains outside handoff

```gherkin
Given an addressed session is closed or its ordinary runtime owner cannot supply a runnable managed execution surface
When a caller attempts handoff
Then the ordinary session-operation boundary refuses or defers the request before successor selection mutates the session
And handoff does not create, reopen, revive, adopt, repair, or reclassify the session or host pane
And no headless or initializing lifecycle transition is authored by handoff
```

#### UC-AH3: Selection reuses fresh-agent dispatch

```gherkin
Given a runnable session records a command and the caller omits a successor
When handoff resolves the successor
Then it uses the existing fresh-agent dispatch policy for that recorded command
And a caller-supplied agent is treated through the existing explicit-preference rules
And a refusal reaches the caller before the predecessor is terminated
```

#### UC-AH4: The native binding rotates without stale projection

```gherkin
Given the predecessor has a native session id and transcript path
When its stop barrier succeeds
Then the predecessor transcript is appended exactly once to the session transcript chain
And the session records the selected successor as active
And the predecessor native session id and current transcript path are cleared before successor launch
And normal successor hooks install the new native session id and transcript path on the same TeleClaude session
And projection never treats the predecessor transcript as the successor's current transcript
```

#### UC-AH5: The successor receives one classified continuation

```gherkin
Given the successor launch is ready to accept its first input
When handoff continues the session
Then it receives exactly one platform-authored handoff envelope through the canonical startup-message delivery path
And the envelope carries the session's command loader when a recorded command exists
And it names the predecessor agent, TeleClaude session id, predecessor transcript when present, and the need to inspect the working tree and re-derive state
And it is classified as platform control rather than human input
And it does not replace the session's last visible human input or reflect onto human conversation surfaces
```

#### UC-AH6: Accepted input waits behind the swap boundary

```gherkin
Given inbound session text is accepted while handoff owns the session runtime boundary
When delivery reaches that session
Then terminal delivery waits until the successor launch and continuation handoff have settled
And accepted rows remain durable and ordered under the unchanged TeleClaude session id
And no accepted input is pasted into the returned shell between predecessor exit and successor readiness
```

#### UC-AH7: Concurrent runtime mutations do not overlap

```gherkin
Given restart, handoff, or runtime restoration already owns one session's runtime boundary
When another runtime mutation targets that session
Then the operations do not overlap their terminal writes or process ownership mutations
And one session never launches two successor agents from one predecessor state
```

#### UC-AH8: Completion and failure report actual progress

```gherkin
Given successor selection succeeds
When the asynchronous handoff is scheduled
Then the caller is told that handoff started and which successor was selected
And completion is emitted only after the successor launch and continuation delivery succeed
And a failure after predecessor termination never restores metadata that falsely claims the stopped predecessor is running
And the session remains inspectable with the last truthful runtime binding
```

#### UC-AH9: Remote handoff negotiates capability before dispatch

```gherkin
Given the session is owned by another computer
When a caller requests handoff on that owner
Then the command transport checks the target's heartbeat-advertised command capabilities through the shared command-capability gate
And a target that does not advertise agent handoff is refused before receiving the command
And a supporting target performs the same in-place swap as a local owner
```

#### UC-AH10: Session-scoped relationships survive unchanged

```gherkin
Given a session participates in reminders, listeners, direct links, parent or child relationships, lineage, or workflow ownership
When its running agent CLI is handed off
Then every durable record remains addressed to the same TeleClaude session id
And handoff reads or changes no todo, slug-holder, hold, relationship, lineage, reminder, listener, link, or adapter record
```

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

- docs/project/spec/feature/agent_runtime/agent-restart.md
- docs/project/spec/feature/agent_runtime/role-aware-agent-dispatch.md
- docs/project/spec/feature/agent_runtime/session-input-delivery.md
- docs/project/spec/feature/tui/session-actions.md
- docs/project/spec/message-headers.md
- docs/project/spec/feature/reconciliation/fleet-cross-version-interop.md
