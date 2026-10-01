---
description: How a help-desk session escalates to the admins of the home that owns its desk — who is notified, what they receive, how their answers reach the visitor on any adapter, and how the conversation returns to the agent.
visibility: public
---

# Help Desk Escalation — Spec

## What it is

A help-desk agent that cannot help its visitor runs `telec sessions escalate`.
The core's agent_runtime context owns the escalation and its relay.
Escalation is a help-desk act: it is accepted from a session running in a help
desk and refused from anywhere else. Admins are its target and never escalate.

An escalation reaches the **admins of the home that owns the desk**:

| Desk                        | Notified                    |
| --------------------------- | --------------------------- |
| Company desk                | that company's admins       |
| Project desk, company-owned | the owning company's admins |
| Project desk, person-owned  | the owning person           |
| Project desk, ownerless     | the platform's admins       |
| Platform desk               | the platform's admins       |

When none of a desk's owning admins can be reached, the platform's admins are
notified instead. Each notified admin receives the escalation in their own
conversation with the platform, on their preferred channel. It names the desk by
kind and slug, the visitor by the name they gave and by the channel they wrote
from, the reason and the summary.

The **relay** runs through the core. While it is active, the visitor's messages
go to the notified admins instead of the agent, whichever adapter the visitor
uses. An admin answers by replying, in their own conversation, to any relay
message they received — the escalation itself or a forwarded visitor message —
and the answer reaches the visitor on the adapter they wrote from. A reply that
tags the agent hands the conversation back: the exchange since the relay started
is delivered to the same help-desk session, the relay ends, and the visitor's
next messages reach the agent again.

A company or project desk's escalation appears on no shared surface. A platform
desk's escalation also opens a thread in the shared Discord guild's escalation
forum, where platform admins can follow and answer it.

## Canonical fields

- **Escalation input** — the visitor's name, the reason, and an optional
  summary, supplied by the agent; the desk, the visitor's channel identity and
  the originating adapter are added by the platform.
- **Relay state** — held by the escalated session: active or not, where each
  notified admin's side of the relay lives, and when the relay started.

### Use cases

#### UC-HDX1: A company desk's escalation reaches that company's admins

```gherkin
Given a customer session in a company's help desk
And that company has two admins and another company has its own admins
When the desk agent escalates with the customer's name and a reason
Then each of the first company's admins receives the escalation in their own conversation with the platform
And it names the company desk, the customer and the channel they wrote from, and the reason
And no admin of the other company is notified
And the escalation appears in no shared Discord forum
```

#### UC-HDX2: A project desk's escalation reaches the admins of the project's owner

```gherkin
Scenario Outline: project owned by <owner>
  Given a customer session in a project's help desk
  And the project is owned by <owner>
  When the desk agent escalates
  Then <recipients> receive the escalation

  Examples:
    | owner                        | recipients                   |
    | a company                    | that company's admins        |
    | a person                     | the owning person            |
    | no one                       | the platform's admins        |
```

#### UC-HDX3: An unreachable owner falls back to the platform's admins

```gherkin
Given a customer session in a company's help desk
And none of that company's admins can be reached from this computer
When the desk agent escalates
Then the platform's admins receive the escalation
And it still names the company desk as its origin
```

#### UC-HDX4: A platform desk visitor below member can be escalated

```gherkin
Given a registered contributor in a platform help-desk session
When the desk agent escalates
Then the escalation is accepted
And the platform's admins receive it
```

#### UC-HDX5: Escalation outside a help desk is refused

```gherkin
Given a session that runs in no help desk
When it runs the escalate command
Then the command is refused, naming that escalation is a help-desk act
And no admin is notified and no relay starts
```

#### UC-HDX6: During a relay the visitor reaches the admins, not the agent

```gherkin
Scenario Outline: visitor on <adapter>
  Given an escalated help-desk session whose visitor writes from <adapter>
  When the visitor sends a message
  Then each notified admin receives it in the conversation that carries the escalation
  And the desk agent does not receive it

  Examples:
    | adapter  |
    | Telegram |
    | Discord  |
    | WhatsApp |
```

#### UC-HDX7: An admin's answer reaches the visitor where they wrote from

```gherkin
Scenario Outline: visitor on <adapter>
  Given an escalated help-desk session whose visitor writes from <adapter>
  When a notified admin replies to a relay message in their own conversation
  Then the visitor receives the reply on <adapter>
  And the desk agent does not receive it

  Examples:
    | adapter  |
    | Telegram |
    | Discord  |
    | WhatsApp |
```

#### UC-HDX8: Handing back resumes the same desk session

```gherkin
Given an escalated help-desk session with an exchange between an admin and the visitor
When an admin replies to a relay message and tags the agent
Then the same help-desk session receives the exchange since the relay started
And the relay ends
And the visitor's next message reaches the desk agent
```

#### UC-HDX9: A failed escalation is reported to the agent

```gherkin
Given a help-desk session for which no admin can be notified
When the desk agent escalates
Then the command fails and the agent is told the escalation did not happen
And the visitor's messages keep reaching the agent
```

#### UC-HDX10: A platform desk escalation is also followed in the shared escalation forum

```gherkin
Given a contributor's session at the platform help desk
When the desk agent escalates
Then the platform's admins are notified in their own conversations
And a thread for the escalation opens in the shared Discord guild's escalation forum
And an answer posted there reaches the contributor like a reply from a notified admin
And tagging the agent in that thread hands the conversation back
```

### Cross-context references

- **identity** — the escalate command's person bands
  (`projects/teleclaude/design/cli-authorization-matrix`) and the owning
  home's admins: a company roster's admins, a project's owner, the platform's
  admins (`projects/teleclaude/design/architecture/scoped-roles`).
- Within agent_runtime: the help-desk session and its placement
  (`projects/teleclaude/spec/feature/agent_runtime/session-lifecycle`), how a
  desk is entered
  (`projects/teleclaude/spec/feature/agent_runtime/conversation-entry`); the
  hand-back arrives through the normal message pipeline.
- **integration** — targeted per-person delivery to each admin's preferred
  channel, delivery of a relayed reply through the visitor's adapter, and the
  shared escalation forum for the platform desk.

## Known caveats

- A notification reaches an admin only through a channel their person
  configuration on the escalating computer resolves.
- An admin whose preferred channel cannot carry a reply, such as email, is
  notified but cannot answer through the relay.
- While any live computer does not yet run this relay, a company or project
  desk's escalation is refused as not available for that desk yet, and a
  platform desk's escalation reaches the platform's admins only through the
  shared escalation thread. Once every live computer runs it, escalation
  behaves as described above.
- A platform desk escalation whose shared thread cannot be opened is still
  accepted when admins were notified in their own conversations, and its
  result tells the agent that the thread is missing.
- A visitor message that no notified admin could receive is refused back to
  the visitor's adapter rather than dropped or handed to the agent; an admin
  answer that could not reach the visitor is reported to that admin, who can
  resend it.
