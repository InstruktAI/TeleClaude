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

A bound open host is inspectable before the agent starts and while its session
is closing. Runtime-established host release makes fresh attachment unavailable
independently of the later final closure. An existing viewer remains inspectable
while its pane survives. A restored open session receives the runtime's current
access answer. Final closure remains the event that releases session-owned state.

This boundary applies `sdlc/policy/domain-ownership`: agent runtime defines host
access and consumers render the published answer. Session listing and finality
remain governed by
`local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle`.

## Canonical fields

The runtime's host-access projection consumes the session's lifecycle,
closed-at marker, and host binding. Its vocabulary and wire representation are
owned by the runtime projection and session API types. The cleanup owner
publishes established host release through the existing binding update path
(`local/projects/teleclaude/spec/feature/agent_runtime/session-cleanup-and-reaping`).
Selection disposition distinguishes inspection, sanctioned headless adoption,
and unavailable access; absence of a binding during close is not adoption.
The access answer consumes the published facts, not an atomic liveness probe.

### Use cases

#### UC-HPA1: Host release and finality remain distinct

```gherkin
Given an agent consumes the host-access answer for an open session whose close is in progress
When runtime-established host release reaches that session's projection before cleanup finishes
Then the answer denies creation of a fresh host viewer
And it does not declare final closure
And the absent host does not authorize headless adoption
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

#### UC-HPA4: A bound closing host remains inspectable

```gherkin
Given an agent consumes the host-access answer for an open closing session
And its host remains bound before runtime-established release
When the agent requests the session's current projection
Then the answer admits inspection through a fresh host viewer
And input terminality does not change that inspection answer
```

## Known caveats

A host can exit after its admission answer is projected. Host liveness,
termination, and recovery remain with their existing runtime owners; the
projection supplies no atomic host-existence guarantee.

A source runtime that has not adopted host-release publication can report a
stale binding until final closure. A receiving projection consumes that source's
facts; the source runtime upgrade supplies the release boundary. A failed
binding publication can leave the previous projection until later finality;
the cleanup owner's error handling reports that failure and continues cleanup.
