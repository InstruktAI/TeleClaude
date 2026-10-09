---
description: How a help-desk session escalates to everyone in its desk's scope — who is notified, the thread in the desk's own escalations forum where a person answers, how answers reach the visitor on any adapter, and how the conversation returns to the agent.
visibility: public
---

# Help Desk Escalation — Spec

## What it is

A help-desk agent that cannot help its visitor runs `telec sessions escalate`.
The core's agent_runtime context owns the escalation and its relay.
Escalation is a help-desk act: it is accepted from a session running in a help
desk and refused from anywhere else.

An escalation reaches **everyone in the desk's scope** — the same people who
see the desk's Discord category
(`local/projects/teleclaude/spec/feature/integration/discord-admin-reflection-state`):

| Desk                        | Notified                                                       |
| --------------------------- | -------------------------------------------------------------- |
| Company desk                | that company's members and admins, the platform's admins       |
| Project desk, company-owned | the owning company's members and admins, the platform's admins |
| Project desk, person-owned  | the owning person, the platform's admins                       |

The agent asks the visitor's name before it escalates. The escalation opens a
thread in the desk's `escalations` forum, named after the visitor, whose first
message is the agent's brief: the desk, the visitor's name and the channel they
wrote from, the reason, the summary, and a link to the visitor's thread in the
desk's `customer-sessions` forum. Each notified person receives a notification
on their preferred channel that links to that thread.

The **thread is the relay**, and it runs through the core. While it is active,
the visitor's messages are posted into the thread instead of reaching the agent,
whichever adapter the visitor uses. A person in the desk's scope answers by
replying in the thread, and the answer reaches the visitor on the adapter they
wrote from. A reply that tags the agent hands the conversation back: the
exchange since the relay started is delivered to the same help-desk session,
the relay ends, and the visitor's next messages reach the agent again. Only the
escalating agent and the people answering speak in the thread.

## Canonical fields

- **Escalation input** — the visitor's name, the reason, and an optional
  summary, supplied by the agent; the desk, the visitor's channel identity and
  the originating adapter are added by the platform.
- **Relay state** — held by the escalated session: active or not, the
  escalation thread, and when the relay started.

### Use cases

#### UC-HDX1: A company desk's escalation reaches that company's scope

```gherkin
Given a customer session in a company's help desk
And that company has members and admins and another company has its own
When the desk agent escalates with the customer's name and a reason
Then a thread named after the customer opens in that desk's escalations forum
And it carries the desk, the customer and the channel they wrote from, the reason, the summary and a link to the customer's session thread
And each member and admin of the company and each platform admin is notified on their preferred channel with a link to the thread
And no one from the other company is notified
```

#### UC-HDX2: A project desk's escalation reaches the scope of the project's owner

```gherkin
Scenario Outline: project owned by <owner>
  Given a customer session in a project's help desk
  And the project is owned by <owner>
  When the desk agent escalates
  Then <recipients> and the platform's admins are notified

  Examples:
    | owner     | recipients                             |
    | a company | that company's members and admins      |
    | a person  | the owning person                      |
```

#### UC-HDX3: An unreachable owner falls back to the platform's admins

#### UC-HDX4: A platform desk visitor below member can be escalated

#### UC-HDX5: Escalation outside a help desk is refused

```gherkin
Given a session that runs in no help desk
When it runs the escalate command
Then the command is refused, naming that escalation is a help-desk act
And no one is notified and no relay starts
```

#### UC-HDX6: During a relay the visitor reaches the thread, not the agent

```gherkin
Scenario Outline: visitor on <adapter>
  Given an escalated help-desk session whose visitor writes from <adapter>
  When the visitor sends a message
  Then it is posted in the desk's escalation thread
  And the desk agent does not receive it

  Examples:
    | adapter  |
    | Telegram |
    | Discord  |
    | WhatsApp |
```

#### UC-HDX7: An answer in the thread reaches the visitor where they wrote from

```gherkin
Scenario Outline: visitor on <adapter>
  Given an escalated help-desk session whose visitor writes from <adapter>
  When a person in the desk's scope replies in the escalation thread
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
Given an escalated help-desk session with an exchange in its escalation thread
When a person in the desk's scope replies in the thread and tags the agent
Then the same help-desk session receives the exchange since the relay started
And the relay ends
And the visitor's next message reaches the desk agent
```

#### UC-HDX9: A failed escalation is reported to the agent

```gherkin
Given a help-desk session whose escalation thread cannot be opened
When the desk agent escalates
Then the command fails and the agent is told the escalation did not happen
And the visitor's messages keep reaching the agent
```

#### UC-HDX10: A platform desk escalation is also followed in the shared escalation forum

#### UC-HDX11: The escalation thread is closed to everyone outside the desk's scope

```gherkin
Given an escalation thread in a company desk's escalations forum
When a person outside that desk's scope looks for it
Then they cannot see it
And a person in the desk's scope can reply in it but cannot open a new thread in the forum
```

### Cross-context references

- **identity** — the escalate command's person bands
  (`local/projects/teleclaude/design/cli-authorization-matrix`) and a desk's
  scope: a company's roster, a project's owner, the platform's admins
  (`local/projects/teleclaude/design/architecture/scoped-roles`).
- Within agent_runtime: the help-desk session and its placement
  (`local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle`), how a
  desk is entered
  (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`); the
  hand-back arrives through the normal message pipeline.
- **integration** — targeted per-person notification on each person's
  preferred channel, the desk's escalations forum and its thread, and delivery
  of a relayed reply through the visitor's adapter
  (`local/projects/teleclaude/spec/feature/integration/discord-admin-reflection-state`).

## Known caveats

- Answering happens only in the escalation thread. A person in scope without a
  bound Discord account is notified but cannot answer.
- A notification reaches a person only through a channel their person
  configuration resolves.
- A visitor message that could not be posted in the escalation thread is refused
  back to the visitor's adapter rather than dropped or handed to the agent; an
  answer that could not reach the visitor, or that arrived after the
  conversation was handed back, is reported in the thread.
