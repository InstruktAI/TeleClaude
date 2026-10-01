---
description: How a conversation on any UI adapter reaches an endpoint — a person's
  assistant or a home's help desk — through one entry identifier, one core resolver,
  and the session that carries both origin and endpoint; the latest entry wins, and
  every miss gets the same neutral reply.
visibility: public
---

# Conversation Entry — Spec

## What it is

Every UI adapter reaches the platform through the same two-level contract,
owned by the core's agent_runtime context, which accepts and places sessions.

**Endpoints.** An endpoint is a routable destination: a registered person's
personal assistant, which runs in that person's home, or a home's help desk.
Each endpoint that can be entered has an **entry identifier**: a member's
invitation token names that member's assistant, and `hd-<kind>-<slug>` names
the help desk of the company or project with that slug. The core keeps the
endpoints and is the only party that resolves an identifier. Resolution yields
the endpoint's working folder and the computer hosting it. An invitation token
also binds the person's platform account the first time it is used (owned by
`local/projects/teleclaude/procedure/member-onboarding`); a help-desk identifier binds
no identity. The platform help desk has no identifier: it is reached by role.

**Conversations.** A conversation is one adapter's private channel with one
person — a chat, a direct-message channel, a phone number. Every session carries
its adapter's origin metadata, and the endpoint it was created at is stamped
beside it. On an adapter whose conversations belong to one computer's bot, the
session is the binding: the adapter finds the person's sessions by origin
metadata. On adapters whose inbound messages reach every computer, the mesh
master alone decides and keeps each conversation's binding in a durable record
of its own, because a session lives only on its host. An adapter's only routing act is to
recognise an entry identifier in what the person sent and hand it to the core;
how the identifier is carried is the adapter's own (see Canonical fields). It
holds no routing rules of its own.

**Entry.** An entry creates a new session at the resolved endpoint, on the
hosting computer, and supersedes the conversation's earlier sessions: a
superseded help-desk session ends, and a superseded assistant session keeps
running but receives no more messages from that conversation. A miss supersedes
nothing, so the conversation stays where it was. A message that carries no
identifier goes to the conversation's **latest session**: the most recently
created session of that conversation that is not superseded, whatever its
state while it is open — starting, active or escalated — found through the
conversation's binding. Because each entry creates a
new session, the latest entry decides where the conversation goes. For a
customer the binding outlives closed sessions, so a returning customer starts a
new session at the desk they last used. A registered member or admin whose
conversation has no open session reaches their own assistant; a registered
contributor or newcomer reaches the platform help desk. An adapter's bare entry
gesture — a start link without a parameter — from a registered member or admin
is an entry to their own assistant; from anyone else it carries no identifier
and routes like any other message. A session that carries no endpoint is never
treated as a desk session to return to.

**Misses.** An identifier that resolves to nothing — no such home, a desk that
is not enabled, a desk hosted by another computer than the one the adapter
reaches, anything that is not exactly an identifier — and a message from an
unregistered person whose conversation has no session, get one **neutral
reply** and no session. The reply is the same text in every one of those cases,
names no organisation, and is sent at most once per conversation within a
cooldown window. An unrecognised invitation token keeps the reply member
onboarding gives it.

**Hosting.** On adapters whose inbound messages reach every computer, the mesh
master decides every entry and supersession, creates the session on the
endpoint's hosting computer, and forwards the conversation's later messages,
files and voice to it. A company or project desk is hosted by a computer that
holds its home with the desk enabled and announces it to the cluster; a
person's assistant and the platform help desk reached through those adapters
are hosted by the mesh master. Only the master routes on these adapters, and
the neutral reply there comes from it. When the master cannot create a session
on the host in time, no binding is made: the person gets the neutral reply and
the conversation keeps its earlier binding. While the master is unavailable,
nothing routes on these adapters: every inbound message gets a
temporarily-unavailable reply, at most once per conversation within a cooldown
window, from the lowest-named live computer that runs the
adapter, no session starts, and conversations resume from the master's durable
record when it returns. On an
adapter whose conversations belong to one computer's bot, that computer decides
alone, and an endpoint's entry link names the hosting computer's bot.

**Cutover.** Master routing on adapters whose messages reach every computer
begins with an explicit, one-way cutover. Until it, every computer handles
those conversations on its own, as it did before master routing: the master
keeps no binding and no computer sends the temporarily-unavailable reply. The
cutover starts once every computer named in the adoption run has exported its
open conversation sessions: the mesh master then activates and publishes the
activation in a shared, durable place. Every computer that learns of it — from
that publication, or from any live computer announcing it — stops handling
those conversations on its own before its next message, including a computer
that was away and returns while the master is unavailable. It announces that
it has only once every message it had already taken on itself has finished. A
computer that cannot read the publication and sees no computer announcing it
cannot tell whether the cutover began, so it handles nothing on its own and
the lowest-named live computer running the adapter sends the
temporarily-unavailable reply. The master starts routing only when every live
computer receiving those adapters has announced it; it then takes every such
computer's export once more and binds each conversation to its newest open
session. A message reaching the master in between waits for the start rather
than being handled twice. A computer away at the start has its sessions bound
once it returns and has announced it; until then a conversation with no
binding may be one of its own, so a message there, whoever sends it, starts no
session and gets the temporarily-unavailable reply instead of the neutral
reply. The unavailability behaviour above applies from activation on.

**Reflection.** Only platform help-desk sessions are reflected into the
platform's shared Discord guild. Company and project help-desk sessions appear
in none of its forums — a project's own forum included — so no tenant's
customer conversation is visible to another
(`local/projects/teleclaude/spec/feature/integration/discord-admin-reflection-state`).

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
  master's durable record of each conversation's endpoint and latest session.
- **Adoption run** — the computers whose exports the cutover waits for, named on
  the mesh master by the `teleclaude.entrypoints.conversation_adoption` module.
- **Resolution result** — the endpoint's working folder and hosting computer.
- **Help-desk entry links** — rendered by `telec config company help-desk-links <slug>`
  and `telec config project help-desk-links <slug>` on a computer hosting the
  enabled desk, one per adapter configured there.

### Use cases

#### UC-CE1: A help-desk identifier opens a session at that desk

```gherkin
Scenario Outline: entry on <adapter>
  Given a project whose help desk is enabled on this computer
  And a person the platform does not know
  When that person enters with the desk's identifier on <adapter>
  Then a customer session is created in that project's help desk on this computer
  And the session carries the person's origin and the desk as its endpoint
  And the person's messages are answered there

  Examples:
    | adapter  |
    | Telegram |
    | Discord  |
    | WhatsApp |
```

#### UC-CE2: A message without an identifier goes to the latest session

```gherkin
Given a conversation whose latest session is at a company's help desk
When the person sends a message that carries no identifier
Then the message reaches that session
And no new session is created
```

#### UC-CE3: The latest entry wins

```gherkin
Given a conversation whose latest session is at one project's help desk
When the person enters with another enabled desk's identifier
Then a new session is created at the other desk
And the earlier desk's session ends
And the person's next messages reach the other desk's session
```

#### UC-CE4: A returning customer lands at the desk they last used

```gherkin
Given an unregistered person whose latest session, now closed, was at a company's help desk
When they send a message that carries no identifier
Then a new customer session is created at that company's help desk
And no neutral reply is sent
```

#### UC-CE5: A member moves between a desk and their own assistant by entry

```gherkin
Given a registered member whose conversation reaches their own assistant
When they enter with a project desk's identifier
Then their messages reach a session at that desk
When they later enter with their own invitation link
Then a new session is created at their own assistant
And their next messages reach it
And the desk session they left has ended
```

#### UC-CE6: Registered people without an open session route by role

```gherkin
Scenario Outline: <role>
  Given a registered person holding the <role> role whose conversation has no open session
  When they send a message that carries no identifier
  Then the message reaches <destination>

  Examples:
    | role        | destination                                          |
    | member      | their own assistant                                  |
    | admin       | their own assistant                                  |
    | contributor | the platform help desk, when that desk is enabled    |
    | newcomer    | the platform help desk, when that desk is enabled    |
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
    | the platform kind      | an identifier naming the platform desk        |
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

```gherkin
Given the platform help desk is not enabled
When a registered contributor without an open session sends a message that carries no identifier
Then they receive the neutral reply
And no session is created
```

#### UC-CE10: Where every computer receives, the mesh master decides and the host serves

```gherkin
Given several computers receive every Discord direct message and every WhatsApp message
And a company desk is hosted by one of them
When a person enters with that desk's identifier
Then the mesh master records the conversation's binding to that desk
And the session is created on the hosting computer
And the person's later messages, files and voice reach that session on its host
And no other computer creates a session or sends a reply
```

#### UC-CE11: An identifier for an endpoint another computer hosts is a miss on a per-computer bot

```gherkin
Given a company desk enabled only on another computer
When a person opens this computer's bot with that desk's identifier
Then they receive the neutral reply
And no session is created on either computer
```

#### UC-CE12: The links command renders a hosted desk's entry links

```gherkin
Given a project whose help desk is enabled on this computer
And Telegram, Discord and WhatsApp are configured here
When an admin of that project runs the help-desk links command for it
Then one link per configured adapter is returned, each carrying the desk's identifier
And the Telegram link names this computer's bot
```

#### UC-CE13: The links command refuses a desk it cannot render

```gherkin
Scenario Outline: <case>
  Given <situation>
  When an admin of the home runs the help-desk links command for it
  Then <outcome>

  Examples:
    | case             | situation                                         | outcome                                                            |
    | disabled         | the home's help desk is not enabled               | the command fails naming that the desk is not enabled              |
    | not hosted here  | the desk is enabled only on another computer      | the command fails naming that this computer does not host the desk |
    | too long         | the desk's identifier exceeds Telegram's limit    | no Telegram link is returned and the other adapters' links are     |
```

#### UC-CE14: Company and project desk sessions stay off shared surfaces

```gherkin
Given a customer session at a company's help desk and a contributor's session at the platform help desk
When the platform reflects sessions into its shared Discord guild
Then the platform desk session is reflected there
And the company desk session appears in no forum of the shared guild, the forum of any project it belongs to included
And a new thread someone opens in the shared forum creates no help-desk session
```

#### UC-CE15: Entering a desk leaves the assistant running

```gherkin
Given a registered member whose personal-assistant session is working on a task
When they enter with a company desk's identifier
Then the assistant session keeps running
And it receives no further messages from that conversation
```

#### UC-CE16: A miss leaves the conversation where it was

```gherkin
Given a conversation whose latest session is at a project's help desk
When the person sends the identifier of a desk that is not enabled
Then they receive the neutral reply
And their next message without an identifier reaches the same project desk session
```

#### UC-CE17: An escalated session is still the conversation's latest session

```gherkin
Given a conversation whose latest session is a help-desk session under escalation
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
  And a session is created at their own assistant

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
    | case                  | situation                                                              | outcome                                                                                       |
    | returning customer    | the mesh master's record binds the conversation to a desk              | a new customer session starts at that desk on its host and no computer sends the neutral reply |
    | stranger              | the mesh master holds no binding for the conversation                  | the mesh master alone sends the neutral reply                                                 |
    | master down, entry    | the mesh master is unavailable and the person enters with an identifier | no binding is made, no session starts, and the lowest-named live computer running the adapter sends the temporarily-unavailable reply |
    | master down, bound    | the mesh master is unavailable and the conversation is already bound   | no session receives the message and the lowest-named live computer running the adapter sends the temporarily-unavailable reply |
    | master back           | the mesh master returns after being unavailable                         | the conversation's next message reaches the session its durable binding names                |
    | host too slow         | the master cannot create the entered desk's session on its host in time | the person receives the neutral reply and the conversation keeps its earlier binding          |
```

#### UC-CE20: A member's bare entry gesture returns them to their assistant

```gherkin
Scenario Outline: <sender>
  Given <sender> whose conversation's latest session is at a project's help desk
  When they use the adapter's start link without a parameter
  Then <outcome>

  Examples:
    | sender                   | outcome                                                                    |
    | a registered member      | a new session is created at their own assistant and their next messages reach it |
    | an unregistered customer | the message goes to the project desk session like any other message        |
```

#### UC-CE21: A desk without an available agent answers with the neutral reply

```gherkin
Given a project's help desk enabled on this computer
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

```gherkin
Scenario Outline: <case>
  Given several computers receive every Discord direct message
  And <situation>
  When a person sends a direct message
  Then <outcome>

  Examples:
    | case                   | situation                                                                                      | outcome                                                                                                   |
    | before the cutover     | the adoption run has not completed                                                             | every computer handles the message as before master routing and none sends the temporarily-unavailable reply |
    | master away, before    | the adoption run has not completed and the mesh master is unavailable                          | every computer handles the message as before master routing                                               |
    | changing over          | the master has activated and a live computer receiving the adapter has not announced it        | the master holds the message until routing starts and no computer handles it on its own                   |
    | returning computer     | the master has activated and a computer returns while the master is unavailable                | that computer learns the activation before handling the message and does not handle it on its own        |
    | newer session          | a computer opened a newer session for the conversation after its first export                  | at the start the conversation is bound to that newer session and the message reaches it                  |
    | still handling         | a computer arms while a message it took on itself is still being handled                       | it announces the cutover only after that message finishes, and the master starts routing only then       |
    | publication unreadable | a computer that has not armed cannot read the publication and sees no computer announcing it   | it handles nothing on its own and the lowest-named live computer sends the temporarily-unavailable reply |
    | source away at start   | a computer named in the adoption run is away when routing starts and the conversation is unbound | whoever sends it, no session starts and the temporarily-unavailable reply is sent until that computer returns |
```

### Cross-context references

- **integration** — each adapter recognises and carries the identifier; a
  per-computer adapter keeps its session lookup by origin metadata, and the
  others hand every message to the mesh master; none resolves anything itself
  (`local/projects/teleclaude/spec/domain/integration`).
- **config** — whether a home runs a desk (`help_desk.enabled`,
  `local/projects/teleclaude/spec/teleclaude-config`) and which computers hold the
  home.
- **identity** — resolves the sender; an unregistered sender on any
  conversation adapter resolves as a customer
  (`local/projects/teleclaude/spec/feature/identity/human-identity-resolution`). The
  links command's standing is configuration target clearance
  (`local/projects/teleclaude/spec/feature/identity/configuration-target-clearance`).
- **context** — what a help-desk session reads
  (`local/projects/teleclaude/spec/feature/context/doc-selection-policy`).
- Placement of restricted sessions:
  `local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle`.

## Known caveats

- Discord carries no identifier in a link: the person sends it as a direct
  message, which needs a Discord account able to open a direct message with the
  bot. Someone who cannot is not reachable through Discord.
- WhatsApp pre-fills the identifier but the person must send it unchanged; an
  edited one gets the neutral reply.
- A WhatsApp endpoint answers only from a computer holding WhatsApp send
  credentials.
