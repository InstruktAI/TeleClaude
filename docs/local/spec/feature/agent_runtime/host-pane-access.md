---
description: Runtime-owned admission for fresh session viewers, distinct from inspection of an existing viewer, agent input readiness, and final session closure.
visibility: internal
delivered_by:
  - stabilize-tui-viewers
---

# Host Pane Access — Spec

## What it is

Agent runtime publishes whether a session admits a fresh viewer of its bound
host pane. Consumers use that answer separately from the lifecycle facts that
describe the session and from the readiness that admits agent input.

A bound initializing host is inspectable before the agent starts. A session
whose close is in progress admits no fresh viewer; an existing viewer remains
inspectable while its pane survives. A restored open session receives the
runtime's current admission answer. Final closure remains the event that
releases session-owned state.

This boundary applies `sdlc/policy/domain-ownership`: agent runtime defines host
access and consumers render the published answer. Session listing and finality
remain governed by
`local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle`.

## Canonical fields

The runtime's host-access projection consumes the session's lifecycle,
closed-at marker, and host binding. Its vocabulary and wire representation are
owned by the runtime projection and session API types. Admission describes the
current lifecycle decision; it is not an atomic observation of host liveness.

### Use cases

#### UC-HPA1: Close admission and finality remain distinct

```gherkin
Given an agent consumes the host-access answer for a session whose close is in progress
When it receives that session's current projection
Then the answer denies creation of a fresh host viewer
And it does not declare final closure
And inspection of an existing surviving viewer remains independent
```

#### UC-HPA2: A bound startup host is inspectable

```gherkin
Given an agent consumes the host-access answer for an open initializing session
And the session has a bound host pane
When it receives that session's current projection before the agent starts
Then the answer admits a fresh host viewer
And the answer does not claim that the agent is ready for input
```

#### UC-HPA3: A failed close restores current access

```gherkin
Given an agent has received denied host-viewer admission during a session close
When the runtime restores the session to an open state with its host bound after close failure
Then the runtime's current host-access projection admits a fresh viewer again
```

## Known caveats

A host can exit after its admission answer is projected. Host liveness,
termination, and recovery remain with their existing runtime owners; the
projection supplies no atomic host-existence guarantee.
