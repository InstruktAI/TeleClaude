---
description: A session holds its agent runtime only while it is needed — a waiting session is parked, giving up its host pane and agent processes while keeping its identity, conversation and place in every listing, and anything delivered to it revives it where it left off.
delivered_by:
  - session-parking
---

# Runtime on Demand — Spec

## What it is

An open session that is waiting costs its whole runtime: its host pane, its
agent CLI and the CLI's helper processes. A **parked** session has given that
runtime up. It keeps its session identity, its native conversation, its role,
its subscriptions and links, and its place in every listing; only the runtime
is gone. It gets a runtime back the moment something needs it.

`parked` is a lifecycle status of its own. It is not `headless`, which means an
agent running outside the platform's host panes, and it is unrelated to the
`idle` agent status. A parked session is open: it is listed, shown and
addressed like any other open session, and nothing closes it because it is
parked.

## Canonical fields

### Parking

A session is parked in one of two ways:

- **Manually.** An operator parks an open session they want to keep without it
  costing anything meanwhile. Parking applies whatever the agent is doing; an
  agent parked during a turn loses that turn the way a restart does, and its
  conversation is kept.
- **Automatically.** An open session whose agent has stayed `idle` for the
  parking idle threshold is parked, unless a client is attached to its host
  pane. A session someone is watching is never parked automatically.

The idle period runs from the moment the agent last became `idle` and restarts
with every agent turn, whatever started it: operator input, a message from
another session, a notification, or a reminder firing. A session whose agent is
`active`, `blocked` or `stalled`, or whose status is not yet known, is not idle.

A designated conversation session that the conversation idle cycle maintains
(`local/projects/teleclaude/spec/feature/agent_runtime/conversation-continuity`)
is not parked automatically; that cycle already frees its runtime on its own
terms.

Parking a session never closes it. Giving up the runtime is not the agent
exiting, so no close, close notification or session-ended processing follows
from it.

### Revival

A parked session is revived when anything is delivered to it — operator or
agent input, a notification, a reminder firing, an event for the procedure it
runs — and when an operator chooses to continue it. Revival starts its agent
again from the session's own native conversation, through the revival contract
(`local/projects/teleclaude/spec/feature/agent_runtime/session-revival`), and
the session leaves `parked`. What was delivered is received by the revived
agent once, in the order it was accepted, under the session-input and
control-delivery contracts
(`local/projects/teleclaude/spec/feature/agent_runtime/session-input-delivery`,
`local/projects/teleclaude/spec/feature/agent_runtime/control-delivery`).

A parked session stays parked across a replacement of the agent_runtime
service. Startup does not restore its runtime; only a delivery or an operator
does.

Closing a parked session closes it without reviving it.

### Use cases

#### UC-ROD1: An operator parks a session to revisit later

```gherkin
Given an operator has an open session they want to keep but are not using
When the operator parks it
Then the session's host pane and agent processes are gone
And the session is still listed, with its status shown as parked
And the session is not closed
```

#### UC-ROD2: An operator's waiting sessions stop costing resources

```gherkin
Given an operator's open session whose agent has been idle for the parking idle threshold
When no client is attached to the session's host pane
Then the session is parked
And a session whose host pane has a client attached is not parked
And a session whose agent is not idle is not parked
```

#### UC-ROD3: An operator continues a parked session

```gherkin
Given an operator has a parked session
When the operator chooses to continue it
Then the session's agent starts again in the same conversation
And the operator can work in it as before it was parked
```

#### UC-ROD4: A message to a parked session reaches its agent

```gherkin
Given a parked session
When an agent acting for a person sends it a message, or a notification or reminder firing is delivered to it
Then the session is revived without any step from its operator
And its agent receives what was delivered once, in the order it was accepted, in the same conversation
```

#### UC-ROD5: A parked session outlasts a platform restart

```gherkin
Given an operator has a parked session
When the agent_runtime service is replaced
Then the session is still parked, with no host pane and no agent process
And a later delivery or the operator's choice to continue it revives it in the same conversation
```

## Known caveats

- **Revival is a cold start.** The agent CLI starts again, which takes a few
  seconds and some CPU; the parking idle threshold exists so that a session in
  active use between messages is not parked.
- **A session that keeps waking itself is not parked automatically.** An agent
  turn started by a reminder firing restarts the idle period, so a session whose
  recurring reminder fires more often than the parking idle threshold stays
  unparked. It can still be parked manually, and its next firing revives it.
