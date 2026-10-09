---
description: How a conversation on any UI adapter reaches an endpoint — a person's
  assistant or a home's help desk — through one entry identifier and one core
  resolver on the master, which hosts every desk; entering continues the person's
  own session there, and every miss gets the same neutral reply.
visibility: public
---

# Conversation Entry — Spec

## What it is

Every UI adapter reaches the platform through the same two-level contract,
owned by the core's agent_runtime context, which accepts and places sessions.

**Endpoints.** An endpoint is a routable destination: a registered person's
personal assistant, which runs in that person's home, or a company's or
project's help desk. Each endpoint has an **entry identifier**: a member's
invitation token names that member's assistant, and `hd-<kind>-<slug>` names the
help desk of the company or project with that slug. The core keeps the
endpoints and is the only party that resolves an identifier. Resolution yields
the endpoint's working folder. An invitation token also binds the person's
platform account the first time it is used (owned by
`local/projects/teleclaude/procedure/member-onboarding`); a help-desk identifier
binds no identity. A registered person is someone the person registry holds
who has the member or admin role at the platform or in a company
(`local/projects/teleclaude/design/architecture/scoped-roles`), and every
registered person has their own assistant.

**Hosting.** Help desks run only on the mesh master. The master hosts every
desk whose home is present on it with the desk enabled; no other computer hosts
a desk, so a desk declared in a repository checked out on several computers has
exactly one host. Every session at a desk runs on the master.

**Conversations.** A conversation is one adapter's private channel with one
person — a chat, a direct-message channel, a phone number. Every session carries
its adapter's origin metadata, and the endpoint it was created at is stamped
beside it. On an adapter whose conversations belong to one computer's bot, that
computer decides alone and finds the person's sessions by origin metadata; a
desk identifier there reaches a desk only when that computer is the master. On
adapters whose inbound messages reach every computer, the mesh master alone
decides: it keeps each conversation's binding in a durable record of its own,
and every other computer handles none of those messages. An adapter's only
routing act is to recognise an entry identifier in what the person sent and hand
it to the core; how the identifier is carried is the adapter's own (see
Canonical fields). It holds no routing rules of its own.

**Routing.** What a person sent decides where it goes, and nothing else does:

| Inbound                                           | Result                                                                                                                                                                |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A desk identifier                                 | That person's latest session at that desk: an open one continues, a closed one is revived, and with none a new one is created. It becomes the conversation's session. |
| An invitation token                               | The person's account is bound, then their own assistant is reached by the same rule.                                                                                  |
| An identifier that resolves to nothing            | The neutral reply; no session.                                                                                                                                        |
| No identifier, and the conversation has a session | That session, revived when it was closed.                                                                                                                             |
| No identifier, no session, a registered person    | Their own assistant, by the same rule.                                                                                                                                |
| No identifier, no session, anyone else            | The neutral reply; no session.                                                                                                                                        |

No other route exists: nobody is sent somewhere by their role, by a desk they
used before, or by a default endpoint. An adapter's bare entry gesture — a start
link without a parameter — from a registered person is an entry to their own
assistant; from anyone else it carries no identifier and routes like any other
message. Entering elsewhere leaves the earlier session as it is; it receives no
more messages from the conversation, and a later entry at its endpoint
continues it. A miss changes nothing, so the conversation stays where it was. A
session is the conversation's session whatever its state while it is open —
starting, active or escalated. A session that carries no endpoint is never
treated as a desk session to return to.

**Misses.** An identifier that resolves to nothing — no such home, a desk that
is not enabled or whose home is not on the master, a desk identifier sent to a
computer's own bot when that computer is not the master, anything that is not
exactly an identifier — and a message without an identifier from a person who is
not registered and whose conversation has no session, get one **neutral reply**
and no session. The reply is the same text in every one of those cases, names no
organisation, and is sent at most once per conversation within a cooldown
window. An unrecognised invitation token keeps the reply member onboarding gives
it.

**Unavailability.** When the master cannot start or revive the session in
time, nothing changes: the person gets the neutral reply and the conversation
keeps its binding. While the master is unavailable, nothing routes on adapters
whose messages reach every computer: every inbound message gets a
temporarily-unavailable reply, at most once per conversation within a cooldown
window, from the lowest-named live computer that runs the adapter, no session
starts or revives, and conversations resume from the master's durable record
when it returns.

**Reflection.** Where help-desk sessions and escalations are reflected in
Discord, and who sees them, is owned by
`local/projects/teleclaude/spec/feature/integration/discord-admin-reflection-state`.

## Canonical fields

- **Entry identifiers** — a member invitation token; `hd-<kind>-<slug>` with
  `<kind>` ∈ `company`, `project`. Matched exactly.
- **How each adapter carries the identifier:**
  - Telegram: the start parameter of the bot link, whose characters and length
    are Telegram's (`third-party/telegram/deep-linking`); an identifier beyond
    them has no Telegram link. A start without a parameter is the bare entry
    gesture.
  - WhatsApp: the message text, pre-filled by the link and sent by the person.
  - Discord: a direct message to the bot consisting of the identifier.
- **Session metadata** — the adapter's origin metadata and the endpoint the
  session was created at.
- **Conversation binding** — on adapters that reach every computer, the mesh
  master's durable record of each conversation's endpoint and session.
- **Resolution result** — the endpoint's working folder.
- **Help-desk entry links** — rendered on the master by
  `telec config company help-desk-links <slug>` and
  `telec config project help-desk-links <slug>`, one per adapter configured
  there.

### Use cases

#### UC-CE1: A help-desk identifier opens a session at that desk

```gherkin
Scenario Outline: entry on <adapter>
  Given a project whose help desk is enabled
  And a person the platform does not know
  When that person enters with the desk's identifier on <adapter> reaching the master
  Then a customer session is created in that project's help desk on the master
  And the session carries the person's origin and the desk as its endpoint
  And the person's messages are answered there

  Examples:
    | adapter  |
    | Telegram |
    | Discord  |
    | WhatsApp |
```

#### UC-CE2: A message without an identifier goes to the conversation's session

```gherkin
Given a conversation whose session is at a company's help desk
When the person sends a message that carries no identifier
Then the message reaches that session
And no new session is created
```

#### UC-CE3: The latest entry wins

```gherkin
Given a conversation whose session is at one project's help desk
When the person enters with another enabled desk's identifier
Then the person's session at the other desk becomes the conversation's session
And the earlier desk's session receives no more messages from the conversation
And the person's next messages reach the other desk's session
```

#### UC-CE4: A returning customer continues their own session

```gherkin
Given an unregistered person whose conversation's session, now closed, is at a company's help desk
When they send a message that carries no identifier
Then that session is revived and receives the message
And no new session is created
And no neutral reply is sent
```

#### UC-CE5: A member moves between a desk and their own assistant by entry

```gherkin
Given a registered member whose conversation reaches their own assistant
When they enter with a project desk's identifier
Then their messages reach their session at that desk
When they later enter with their own invitation link
Then their own assistant's session becomes the conversation's session again
And their next messages reach it
```

#### UC-CE6: A registered person without a session reaches their own assistant

```gherkin
Scenario Outline: <person>
  Given <person> whose conversation has no session
  When they send a message that carries no identifier
  Then <outcome>

  Examples:
    | person                                                         | outcome                                  |
    | a person holding the member role at the platform               | the message reaches their own assistant  |
    | a person holding the admin role in a company and no platform role | the message reaches their own assistant  |
    | a person the registry holds with no role at the platform or in any company | they receive the neutral reply and no session is created |
```

#### UC-CE7: Every miss gets the same neutral reply and no session

```gherkin
Scenario Outline: <case>
  Given a person the platform does not know, whose conversation has no session
  When the person sends <message>
  Then they receive the neutral reply
  And the reply is identical across every case below
  And the reply names no organisation
  And no session is created

  Examples:
    | case                   | message                                       |
    | no identifier          | a greeting                                    |
    | unknown home           | the identifier of a slug no home declares     |
    | disabled desk          | the identifier of a home whose desk is off    |
    | not exactly one        | an identifier with changed case or a typo     |
```

#### UC-CE8: The neutral reply is not repeated within its cooldown

```gherkin
Given a person received the neutral reply in a conversation
When they send more messages that reach no endpoint within the cooldown window
Then they receive no further reply in that window
And a message after the window may receive the neutral reply once more
```

#### UC-CE9: Contributors get the neutral reply when the platform desk is off

#### UC-CE10: Where every computer receives, the master decides and hosts

```gherkin
Given several computers receive every Discord direct message and every WhatsApp message
When a person enters with a company desk's identifier
Then the mesh master records the conversation's binding to that desk
And the person's session at that desk runs on the master
And the person's later messages, files and voice reach that session
And no other computer creates a session or sends a reply
```

#### UC-CE11: A desk identifier on a computer's own bot reaches a desk only on the master

```gherkin
Given a computer that is not the master and runs its own bot
When a person opens that bot with an enabled desk's identifier
Then they receive the neutral reply
And no session is created on any computer
```

#### UC-CE12: The links command renders a desk's entry links on the master

```gherkin
Given a project whose help desk is enabled
And Telegram, Discord and WhatsApp are configured on the master
When an admin of that project runs the help-desk links command for it on the master
Then one link per configured adapter is returned, each carrying the desk's identifier
And the Telegram link names the master's bot
```

#### UC-CE13: The links command refuses a desk it cannot render

```gherkin
Scenario Outline: <case>
  Given <situation>
  When an admin of the home runs the help-desk links command for it
  Then <outcome>

  Examples:
    | case             | situation                                         | outcome                                                          |
    | disabled         | the home's help desk is not enabled               | the command fails naming that the desk is not enabled            |
    | not the master   | the command runs on a computer that is not master | the command fails naming that help desks run on the master       |
    | too long         | the desk's identifier exceeds Telegram's limit    | no Telegram link is returned and the other adapters' links are   |
```

#### UC-CE14: Company and project desk sessions stay off shared surfaces

#### UC-CE15: Entering a desk leaves the assistant running

```gherkin
Given a registered member whose personal-assistant session is working on a task
When they enter with a company desk's identifier
Then the assistant session keeps running
And it receives no further messages from that conversation
```

#### UC-CE16: A miss leaves the conversation where it was

```gherkin
Given a conversation whose session is at a project's help desk
When the person sends the identifier of a desk that is not enabled
Then they receive the neutral reply
And their next message without an identifier reaches the same project desk session
```

#### UC-CE17: An escalated session is still the conversation's session

```gherkin
Given a conversation whose session is a help-desk session under escalation
When the person sends a message that carries no identifier
Then the message reaches that session's relay
And no new session is created and no neutral reply is sent
```

#### UC-CE18: An invitation token enters the member's assistant on every adapter

```gherkin
Scenario Outline: invitation on <adapter>
  Given a registered member whose <adapter> account is not yet bound to them
  When they enter with their invitation token on <adapter>
  Then their <adapter> account is bound to them
  And their own assistant's session becomes the conversation's session

  Examples:
    | adapter  |
    | Telegram |
    | Discord  |
    | WhatsApp |
```

#### UC-CE19: Where every computer receives, only the master routes and one computer replies when it cannot

```gherkin
Scenario Outline: <case>
  Given several computers receive every WhatsApp message
  And <situation>
  When the person sends a message that carries no identifier
  Then <outcome>

  Examples:
    | case                  | situation                                                                  | outcome                                                                                                                              |
    | returning customer    | the mesh master's record binds the conversation to a closed desk session    | that session is revived on the master and no computer sends the neutral reply                                                       |
    | stranger              | the mesh master holds no binding for the conversation                      | the mesh master alone sends the neutral reply                                                                                        |
    | master down, entry    | the mesh master is unavailable and the person enters with an identifier     | no binding is made, no session starts, and the lowest-named live computer running the adapter sends the temporarily-unavailable reply |
    | master down, bound    | the mesh master is unavailable and the conversation is already bound       | no session receives the message and the lowest-named live computer running the adapter sends the temporarily-unavailable reply      |
    | master back           | the mesh master returns after being unavailable                            | the conversation's next message reaches the session its durable binding names                                                       |
    | master too slow       | the master cannot start or revive the session in time                      | the person receives the neutral reply and the conversation keeps its binding                                                         |
```

#### UC-CE20: A member's bare entry gesture returns them to their assistant

```gherkin
Scenario Outline: <sender>
  Given <sender> whose conversation's session is at a project's help desk
  When they use the adapter's start link without a parameter
  Then <outcome>

  Examples:
    | sender                   | outcome                                                                           |
    | a registered member      | their own assistant's session becomes the conversation's session and receives their next messages |
    | an unregistered customer | the message goes to the project desk session like any other message               |
```

#### UC-CE21: A desk without an available agent answers with the neutral reply

```gherkin
Given a project's help desk enabled on the master
And no agent in the dispatch order for desk sessions is available
When a person enters with that desk's identifier
Then no session is created
And the person receives the neutral reply
```

#### UC-CE22: A registered member at a desk is confined like a customer

```gherkin
Given a registered member who entered a project desk with its identifier
When the desk session's agent runs
Then the session is confined to its desk exactly as a desk session below member is
And the member's own role widens none of that confinement while the session stays at the desk
```

#### UC-CE23: Master routing begins at the cutover and never runs beside per-computer handling

#### UC-CE24: Re-entering a desk continues the person's session there

```gherkin
Given a person whose session at a project's help desk was closed
And their conversation's session is now elsewhere
When they enter with that desk's identifier again
Then that desk session is revived
And no new session is created
And it becomes the conversation's session
```

#### UC-CE25: A desk has one host whatever computers hold its repository

```gherkin
Given a project whose help desk is enabled
And the project's repository is checked out on several computers, the master included
When people enter with that desk's identifier on any adapter
Then every session at the desk runs on the master
And no other computer hosts the desk or refuses entry because of another host
```

### Cross-context references

- **integration** — each adapter recognises and carries the identifier; a
  per-computer adapter keeps its session lookup by origin metadata, and the
  others hand every message to the mesh master; none resolves anything itself
  (`local/projects/teleclaude/spec/domain/integration`).
- **config** — whether a home runs a desk (`help_desk.enabled`,
  `local/projects/teleclaude/spec/teleclaude-config`) and whether the master
  holds the home.
- **identity** — resolves the sender; an unregistered sender on any
  conversation adapter resolves as a customer
  (`local/projects/teleclaude/spec/feature/identity/human-identity-resolution`). The
  links command's standing is configuration target clearance
  (`local/projects/teleclaude/spec/feature/identity/configuration-target-clearance`).
- **context** — what a help-desk session reads
  (`local/projects/teleclaude/spec/feature/context/doc-selection-policy`).
- Placement, closing and revival of sessions:
  `local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle` and
  `local/projects/teleclaude/spec/feature/agent_runtime/session-revival`.

## Known caveats

- Discord carries no identifier in a link: the person sends it as a direct
  message, which needs a Discord account able to open a direct message with the
  bot. Someone who cannot is not reachable through Discord.
- WhatsApp pre-fills the identifier but the person must send it unchanged; an
  edited one gets the neutral reply.
- A WhatsApp endpoint answers only from a computer holding WhatsApp send
  credentials, so the master holds them.
- A desk whose home is not present on the master is not hosted anywhere: its
  identifier gets the neutral reply until the home is on the master.
- One WhatsApp business number serves every desk, so a desk link can only
  pre-fill the identifier for the person to send. A desk with its own channel
  identity — its own number or bot — is not supported.
