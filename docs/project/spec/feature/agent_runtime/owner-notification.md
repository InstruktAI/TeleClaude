---
description: "Owner-targeted ephemeral notification an agent working a todo pushes to that todo's human owner via `telec todo notify`, carrying a message and a `discord://` back-link into the invoking session — a live agent when a decision is pending, a best-effort transcript link otherwise."
visibility: 'public'
delivered_by:
  - todo-notify-owner
---

# Owner Notification — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

**Owner notification** is the capability by which an agent working a todo pushes a
single, ephemeral notification to that todo's **human owner** — the chain-root
human already resolvable from the todo's lineage and injected into the agent's
session. The push carries the agent's message and a back-link into the invoking
session, so the owner is actively told (rather than left to notice a waiting
session) and has a one-click path back into the conversation.

The public surface is a purpose-built agent CLI verb — `telec todo notify
<message>`. The verb is the **authorization boundary**: it is the only path by
which an agent emits an owner notification with system provenance. The event and
notification-delivery pipeline stays below the verb; agents do not emit raw
events, so a system-fact notification can never be forged.

The notification is **ephemeral** — a single push carrying no lifecycle machinery
of its own. The session itself is the beacon; the back-link is the target.
Delivery rides the **existing notification cartridge / notification-delivery
pipeline** to the owner's active push channel(s); no new delivery mechanism is
introduced. The back-link is a `discord://` deep link into the invoking session's
Discord channel, crafted via the shared session deep-link helper (owned by the
`telec message` primitive and reused here).

The awareness-vs-decision-needed distinction is **emergent, not a flag**: when the
agent needs a decision it stays alive and waiting, so the back-link lands the owner
on a live agent to converse with; when the agent only raised awareness and then
continued to completion, its session self-removes on success and the same back-link
best-effort resolves. The agent's own behavior plus session state carry the
distinction — no parameter selects it.

## Canonical fields

### Use cases

#### UC-ON1: Agent notifies its todo's owner

```
Given an agent is working a todo whose human owner is resolvable from the todo's chain-root lineage
When the agent invokes `telec todo notify "<message>"` from within its session
Then the owner is resolved by the system from the todo's human lineage, not from any agent-supplied recipient
And a single notification is created carrying the message
And it is delivered to the owner through the existing notification-delivery pipeline on the owner's active channel(s)
And the notification carries a back-link into the invoking session
```

#### UC-ON2: Back-link is a Discord deep link into the invoking session

```
Given an owner notification delivered from an agent's session
When the owner follows the back-link
Then the back-link is a `discord://` deep link into that session's Discord channel
And it is crafted via the shared session deep-link helper rather than re-implemented
```

#### UC-ON3: Decision-needed — the back-link lands on a live agent

```
Given an agent invoked `telec todo notify` because it reached a decision that is genuinely the owner's to make
And the agent then holds and goes idle-but-alive, its session remaining present as a beacon
When the owner follows the back-link
Then the session is still present
And the owner lands on the live agent and can converse with it directly
And no flag on the notify invocation was required to produce this outcome
```

#### UC-ON4: Awareness-only — the back-link best-effort resolves

```
Given an agent invoked `telec todo notify` only to raise awareness of a grounded call it already made
And the agent then continued its work to successful completion
And the session self-removed on successful completion
When the owner follows the back-link
Then the link best-effort resolves
And a Discord "not found" outcome for the finished, self-removed session is accepted and expected
And no liveness check or fallback gates emission or supplements the back-link
```

#### UC-ON5: Provenance by construction

```
Given an agent session
When the agent seeks to emit an owner notification carrying system provenance
Then the sanctioned `telec todo notify` verb is the only path that produces it
And raw event emission is not exposed to the agent
And the agent has no alternative path by which to forge the same system-fact notification
```

#### UC-ON6: Ephemeral push — no lifecycle of its own

```
Given an agent invokes `telec todo notify "<message>"`
When the notification is emitted
Then exactly one push is produced
And it carries no notify-specific lifecycle state, todo-state transition, or machinery of its own beyond the durable row the notification-delivery pipeline already keeps for any notification
And the invoking session remains the beacon the back-link targets
```

#### UC-ON7: Distinct from customer escalation

```
Given the existing `telec sessions escalate` surface routes a customer conversation to a human admin
When an agent invokes `telec todo notify "<message>"`
Then the todo's human owner is targeted, not an admin
And invoking notify never triggers escalate
And the `telec sessions escalate` behavior and audience are unchanged
```
