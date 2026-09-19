---
description: Hand a TeleClaude session to a different agent under the same session
  id — a fresh successor launch whose transcript chains onto the predecessor's, with
  ownership, child links, claims, and lineage untouched.
visibility: public
---

# Agent Handoff — Spec

## What it is

Agent handoff is the cross-agent form of agent restart. A caller asks the agent_runtime service to restart a session with a handoff, naming a successor agent or leaving the choice to the platform. The service selects the successor, terminates the predecessor's agent process, and launches the successor fresh — without resuming any native session — inside the same TeleClaude session row and host pane. The predecessor's native transcript joins the session's transcript chain when the successor announces its first checkpoint, so the session presents one continuous history under one id.

Handoff is a session operation. It never reads todo state, slug holders, or hold state. Ownership, initiator and child links, live claims, and lineage survive because none of them key on the agent. Whether to hand off, and whether to hand off a closed session, is the caller's decision; the platform never triggers a handoff on its own.

A live session is swapped in place. A closed session is revived through restart's existing revive path and then swapped. The successor's first input is a platform-generated brief in the ordinary dispatch shape, so it learns what it is picking up and where to read before it acts.

## Canonical fields

### Use cases

#### UC-AH1: A live session continues under a different agent with its identity intact

```gherkin
Given an agent caller holds restart clearance for a live session
When the caller asks for a restart with a handoff
Then the session id is unchanged
And the session's initiator link, its children's parent links, any live slug claim it holds, and its lineage are exactly what they were
And the predecessor's agent process is no longer running
And the session reports the successor as its active agent once the successor announces its first checkpoint
```

#### UC-AH2: A closed session is revived and continued under a different agent

```gherkin
Given a session whose row is marked closed
When an agent caller asks for a restart with a handoff
Then the closed marker is cleared and the session is brought back with a host pane
And the successor is launched into that pane
And the identity guarantees of a live-session handoff hold
```

#### UC-AH3: The successor starts fresh and the transcript chain stays continuous

```gherkin
Given a session with a recorded native transcript is handed off
When the successor launches
Then it launches without resuming any native session
And once the successor announces its first checkpoint, the session's native identity is the successor's
And the predecessor's native transcript is part of the session's transcript chain
And a chain-aware transcript read presents the predecessor's history followed by the successor's
```

#### UC-AH4: Automatic selection is the existing dispatch resolution

```gherkin
Given a caller asks for a restart with a handoff and names no successor
When the service selects the successor
Then the successor is whatever the existing fresh-session dispatch resolution returns for the session's recorded command
And the caller is told which successor was selected
```

#### UC-AH5: A dispatch refusal leaves the session untouched

```gherkin
Given a caller asks for a restart with a handoff
And the existing dispatch resolution returns a refusal
When the service handles that result
Then the refusal reaches the caller before any process is terminated
And the session's agent, lifecycle state, and host pane are exactly as they were
```

#### UC-AH6: Explicit selection is the existing dispatch resolution

```gherkin
Given a caller asks for a restart with a handoff and names a successor
When the service resolves the successor
Then the outcome is whatever the existing dispatch resolution returns for an explicitly named agent, including its existing not-available response
And nothing is terminated before that resolution settles
```

#### UC-AH7: The successor is briefed in the ordinary dispatch shape

```gherkin
Given a session with a recorded command is handed off
When the successor becomes ready for input
Then its first input is the ordinary dispatch shape for the session's recorded command and working slug
And the additional context names the previous agent and the session id
And it states whether the session was live or closed at handoff and for how long
And it carries the predecessor's native transcript path as the only transcript pointer, with the instruction to read its tail first
And it warns that a worktree may hold uncommitted predecessor work
And it instructs the successor to re-derive state through the role command
```

#### UC-AH8: A predecessor without a transcript is reported, not pointed at

```gherkin
Given a session is handed off before its predecessor recorded a native transcript
When the successor is briefed
Then the brief states that no predecessor transcript exists
And it carries no transcript pointer
And the remaining handoff context is unchanged
```

#### UC-AH9: A session without a recorded command receives the handoff context alone

```gherkin
Given a session with no recorded command is handed off
When the successor is briefed
Then its first input carries the handoff context and no command loader
```

#### UC-AH10: Handoff of a remotely owned session runs on the owner

```gherkin
Given a session is owned by a remote computer
When an agent caller asks for a restart with a handoff and names the owning computer
Then the handoff is performed on the owning computer
And the acceptance response and completion event are the same the caller would receive for a local handoff
And no handoff is attempted against the local computer
```

#### UC-AH11: Handoff never consults workflow state

```gherkin
Given a session with no todo association
When an agent caller asks for a restart with a handoff
Then the handoff proceeds exactly as for a session that drives a todo
And no todo, slug-holder, or hold record is read or changed by the operation
```

<!-- planned:session-handoff-state-convergence -->
#### UC-AH12: The successor adopts the existing session before its hooks can diverge

```gherkin
Given successor selection succeeded and the predecessor process exited
When the service prepares the fresh successor launch
Then the existing session row records the selected successor as its active agent
And the predecessor's provider-bound native session identifier is released before the successor can emit a hook
And the predecessor's native transcript remains available as the transcript-chain source
When the successor announces its native metadata
Then that event resolves to the existing TeleClaude session id
And the metadata updates only the successor's native session identifier and transcript
And the session continues to report the already-selected successor as its active agent
And the predecessor transcript is appended to the session's transcript chain
And no replacement session identity is minted and no successor hook is dropped
```
<!-- /planned:session-handoff-state-convergence -->

<!-- planned:session-handoff-state-convergence -->
#### UC-AH13: Handoff preserves every session-scoped behavior

```gherkin
Given an agent session has pending input or control delivery, active conversation links or listeners, reminders, parent or child relationships, workflow ownership, or other behavior addressed to its TeleClaude session id
When that session is handed to a different agent
Then every durable record remains addressed to the same TeleClaude session
And accepted input and control delivery continue in order without loss or duplication
And later activity and turn completion trigger the same links, listeners, parent attention, workflow transitions, attribution, and projections as if the predecessor agent had continued
And only the active agent, its native session identity, and the transcript chain change
```
<!-- /planned:session-handoff-state-convergence -->

### Cross-context references

- **workflow** — orchestrator ownership and owned-slug resolution key on session row fields the handoff preserves; workflow observes the same session before and after, with a different active agent.
- **session_mirrors** — the transcript chain widens by one native transcript per handoff, exactly as it does per revival; the mirror layer threads continuity through the chain.
- **identity** — handoff runs under the restart clearance; the initiator link and lineage on the session row are untouched.
- **presentation** — the TUI exposes the three handoff gestures under `project/spec/feature/tui/session-actions`.

## Known caveats

- The successor has no memory of the predecessor's turn. It inherits context by reading the chained transcript the brief points at, never by native resume.
- Selection happens before termination. A refused handoff leaves the predecessor exactly as it was, including a stalled one.
- Handoff carries no policy about when to hand off. Detection of provider exhaustion and orchestration recovery guidance are separate concerns that call this operation.
- Kill-side and readiness failures are the restart contract's failures and reach the operator through the restart-failure notifications in `project/spec/feature/agent_runtime/agent-restart`.

## See Also

- docs/project/spec/feature/agent_runtime/agent-restart.md — the same-agent restart this operation extends.
- docs/project/spec/feature/agent_runtime/session-revival.md — the revive path a closed-session handoff reuses.
- docs/project/spec/feature/agent_runtime/role-aware-agent-dispatch.md — the dispatch resolution handoff reuses as it is for both the automatic and the explicit form.
- docs/project/spec/feature/agent_runtime/model-quota-recovery.md — same-agent model fallback, which handoff complements rather than replaces.
- docs/project/spec/feature/tui/session-actions.md — the TUI gestures that invoke handoff.
