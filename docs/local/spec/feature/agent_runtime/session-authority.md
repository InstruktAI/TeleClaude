---
description: Which session may act on which — a standing role has no session above
  it, and no session acts on the orchestrator that dispatched it.
visibility: internal
---

# Session Authority — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

A session record answers two separate questions with one value: which session
started this one, and which session commands it. This surface separates them.

**Dispatch** is the fact that one session asked for another to exist. It is
recorded so a completed turn can wake the asking session and so a dispatcher can
account for what it set in motion.

**Command** is the authority to end, restart, interrupt, or unsubscribe from a
session. It follows the mandate under which a session works, never the act that
started it.

Two rules express the separation. A **standing session** — one whose role is of
the standing class, the integrator and the project coordinator, or a scheduled
job's session whatever its role
(`local/projects/teleclaude/spec/feature/identity/agent-roles`) — takes its
work from a queue, a schedule, or the fleet, so the session that started it
conferred no mandate and none is recorded. And an orchestrator's authority
runs downward only: a session never acts on the orchestrator that dispatched it,
because that dispatch confers the mandate the session works under, and the act
would reach past that mandate into the orchestrator's own. Any other dispatch
confers no mandate: a peer a session asks for, or a session a standing,
human-directed or non-orchestrating session starts, acts on the session that
started it, and on every session further up the chain, as on any other session
within its reach. Upward
reporting needs no act — a completed turn already wakes the session above.

A focused session — one whose role is of class `focused`
(`local/projects/teleclaude/spec/feature/identity/agent-roles`) — acts on no
other session, on its own computer or another: it neither messages nor links
to one, and its own computer refuses its requests to do so with a refusal that names its own output and artifacts as its
reporting path. Reading a named session's transcript, which a focused role may
add for its assignment, acts on no session. It reports through its own completed turn and its artifacts,
and the session that dispatched it reads them and routes whatever must reach
anyone else, so two focused sessions never form a conversation of their own.
Orchestrating and standing sessions keep acting downward and sideways, and so
does a session with nothing above it, reaching anywhere in the fleet.

Standing sessions have no dispatch parent or human-origin identity; they resolve
to the platform principal. Adopting a live session into a standing role clears
its prior human identity. A standing session is not an ordinary dispatched
child, so ending its former starter does not end it. Direct requests to message,
link to, unsubscribe from, end, or restart the orchestrator that dispatched the caller are refused;
a session reports upward to an orchestrator through its own completed turn
(`local/projects/teleclaude/spec/feature/identity/principal-resolution`).

## Canonical fields

### Ubiquitous language

**Standing session**
: A session whose work arrives from a queue, a schedule, or the fleet rather than
from a dispatcher: one carrying a standing-class role — the integrator, the
project coordinator — or a scheduled job's session.

**Dispatch chain**
: The sessions between a session and the fleet root, walked through the
session-above-it link. A session's **ancestors** are every session on that walk;
the session itself is not among them.

**Orchestrator**
: A session whose role the catalog assigns todo orchestration: the lifecycle orchestrators and their intake, architecture and planning phases (`local/projects/teleclaude/spec/feature/identity/agent-roles`). The integrator and the project coordinator are not orchestrators for this rule.

**Upward act**
: A request naming the orchestrator that dispatched the calling session as its target.

### Use cases

#### UC-SA1: A standing session has no session above it, whatever door opened it

#### UC-SA2: A standing session survives the cleanup of the session that started it

#### UC-SA3: An agent can report a result to its dispatcher within its mandate

```gherkin
Given an orchestrator's child agent acting for a person needs to report a result to the orchestrator
When it tries to message the orchestrator directly
Then the request is refused and names the agent's own output as the reporting path
And the dispatcher receives the result when the child completes its turn
And the dispatcher remains unchanged
```

#### UC-SA4: An operator can have an agent manage a session within its reach

```gherkin
Given an operator asks their agent to restart a peer or child session
When that target is not the orchestrator that dispatched the agent
Then the restart request proceeds
And a rootless agent can reach any session in the fleet
And targeting itself is not treated as an upward act
```

### Known caveats

- **The dispatch chain is read where the sessions are recorded.** A chain that
  crosses a computer boundary is walked only as far as the records the deciding
  computer holds. This matches the reach the claiming group already has, and it
  is the reason the refusal is a guard on a known-upward target rather than a
  proof that a target is not upward.
- **Dispatch and notification are separate axes.** Suppressing a dispatcher's
  notifications does not remove the session above; removing the session above
  does not by itself silence a subscription taken out some other way.

## See Also

- docs/local/spec/feature/agent_runtime/session-lifecycle.md — creation, listing, and the caller-scoped termination this surface keeps standing sessions out of.
- docs/local/spec/feature/identity/self-end-authorization-bypass.md — the self-end allowance a session with nothing above it relies on.
- docs/local/spec/feature/agent_runtime/direct-conversation-links.md — link closure, which this surface narrows.
- docs/local/design/architecture/ai-to-ai-dispatch.md — the dispatch flow and its invariants.
- ~/.teleclaude/docs/general/principle/session-lifecycle.md — why a governed session does not end itself, and what governance is.
