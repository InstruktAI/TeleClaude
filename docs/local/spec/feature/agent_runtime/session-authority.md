---
description: Which session may act on which — a standing role has no session above
  it, and no session acts on the session above it.
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

<!-- planned-change:procedure-role-capability-composition -->

Two rules express the separation. A **standing role** — the integrator, the
project coordinator, a scheduled job runner — takes its work from a queue, a
schedule, or the fleet, so the session that started it conferred no mandate and
none is recorded. And authority runs downward and sideways only: a session never
acts on a session above it in the dispatch chain, because the act would reach
past its own mandate into the one that dispatched it. Upward reporting needs no
act — a completed turn already wakes the session above.
<!-- change:procedure-role-capability-composition -->

Two rules express the separation. A **standing session** — one whose role is of
the standing class, the integrator and the project coordinator, or a scheduled
job's session whatever its role
(`local/projects/teleclaude/spec/feature/identity/agent-roles`) — takes its
work from a queue, a schedule, or the fleet, so the session that started it
conferred no mandate and none is recorded. And authority runs downward and
sideways only: a session never acts on a session above it in the dispatch
chain, because the act would reach past its own mandate into the one that
dispatched it. Upward reporting needs no act — a completed turn already wakes
the session above.
<!-- /planned-change:procedure-role-capability-composition -->

Peers are unaffected: a reviewer and a builder, and a driver and the peer it
dispatched, all keep talking. So does a session with
nothing above it, reaching anywhere in the fleet.

## Canonical fields

### Ubiquitous language

<!-- planned-change:procedure-role-capability-composition -->

**Standing role**
: A role whose work arrives from a queue, a schedule, or the fleet rather than
from a dispatcher: the integrator, the project coordinator, and a scheduled job
runner.
<!-- change:procedure-role-capability-composition -->

**Standing session**
: A session whose work arrives from a queue, a schedule, or the fleet rather than
from a dispatcher: one carrying a standing-class role — the integrator, the
project coordinator — or a scheduled job's session.
<!-- /planned-change:procedure-role-capability-composition -->

**Dispatch chain**
: The sessions between a session and the fleet root, walked through the
session-above-it link. A session's **ancestors** are every session on that walk;
the session itself is not among them.

**Upward act**
: A request naming an ancestor of the calling session as its target.

### Use cases

#### UC-SA1: A standing session has no session above it, whatever door opened it

<!-- planned-change:procedure-role-capability-composition -->

```gherkin
Given a session takes a standing role — the integrator, the project coordinator, or a scheduled job runner
And the role arrives through any door: an automatic spawn, an agent's directed start, a human's directed start, or adoption by a session already running
When that session carries the role
Then no session is recorded above it
And the session that started it is not woken by its completed turns
And no human identity is recorded on the session, its work having arrived from a queue, a schedule, or the fleet rather than from a person
And the session resolves to the platform's principal, `system:daemon`, shared by every session with no human origin
And a session adopted into the role while running stops carrying the human identity it held, from the moment of adoption
```

<!-- change:procedure-role-capability-composition -->

```gherkin
Given a session becomes standing — it carries the integrator or project coordinator role, or it is a scheduled job's session
And the role arrives through any door: an automatic spawn, an agent's directed start, a human's directed start, or adoption by a session already running
When that session carries the role
Then no session is recorded above it
And the session that started it is not woken by its completed turns
And no human identity is recorded on the session, its work having arrived from a queue, a schedule, or the fleet rather than from a person
And the session resolves to the platform's principal, `system:daemon`, shared by every session with no human origin
And a session adopted into the role while running stops carrying the human identity it held, from the moment of adoption
```

<!-- /planned-change:procedure-role-capability-composition -->

#### UC-SA2: A standing session survives the cleanup of the session that started it

```gherkin
Given an agent session started a standing session and also holds ordinary dispatched children
When that agent ends its child sessions without naming one
Then its ordinary children are closed
And the standing session keeps running
```

#### UC-SA3: An act on a session above the caller is refused, and the refusal names the alternative

```gherkin
Given an agent session has a session above it in the dispatch chain
When it asks to message that session, to open or close a direct conversation with it, to unsubscribe from it, to end it, or to restart it
Then the request is refused before it takes effect
And the refusal states that a completed turn already reaches the session above, so the result belongs in the caller's own output
And the target session is unchanged
```

#### UC-SA4: Peer, downward, and rootless acts are unchanged

```gherkin
Given an agent session names a target that is not above it in the dispatch chain
When it messages, opens or closes a direct conversation with, unsubscribes from, ends, or restarts that target
Then the request proceeds exactly as before
And a session with nothing above it reaches any session in the fleet
And a session naming itself is never treated as acting upward
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
