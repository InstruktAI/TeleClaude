---
description: Master-owned conversational entry for Telegram, WhatsApp, Discord DMs and designated assistant channels, with durable endpoint bindings and silent non-master receivers.
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

**Hosting.** The mesh's unique master owns conversational entry for Telegram,
WhatsApp, Discord direct messages and designated Team assistant channels. It
resolves, creates, revives and binds those conversations and hosts their
assistant or desk runtime. Ownership follows the configured master through the
existing fleet resolver, independently of how many computers receive a provider
event (`general/principle/trust-and-guardrails`).

**Two planes.** Conversations with people are the master's: insiders converse
through Discord direct messages, designated Team channels and personal voice
rooms (`local/projects/teleclaude/spec/feature/integration/discord-personal-voice-conversation`),
outsiders through Telegram and WhatsApp. Each computer's operator console — its
Discord project forums
(`local/projects/teleclaude/spec/feature/integration/discord-interaction-ownership`)
and its TUI — is its own and keeps working without the others. Discord
therefore runs one bot on every computer under a local configuration scope
(`local/projects/teleclaude/spec/teleclaude-config`), and the master's ownership
of Discord direct messages and Team channels is the owner rule above, never a
property of that configuration.

**Conversations.** A conversation is one adapter's designated channel with one
person. The session records its adapter identity and resolved endpoint. The
master retains the channel's durable binding. An adapter carries the person's
input, recognised entry identifier, channel identity and verified designation
to the core; the core owns endpoint resolution and routing
(`sdlc/principle/design-fundamentals`).

A non-master receiver ignores conversational input before session lookup or
creation, invitation redemption, identity binding, media retrieval, transcription
or user-visible feedback. It forwards no such input to another computer.
Discord computer-owned forums and their controls follow their resource owner
under `local/projects/teleclaude/spec/feature/integration/discord-interaction-ownership`.
Receiving an event is transport observation, not ownership of its effects.

**Discord.** Discord is a members' surface and never a customer's, so it carries
no desk entry: a desk identifier sent on Discord is a miss, and a Discord
conversation is never bound to a desk session. Customers reach a desk through
Telegram and WhatsApp.

**Routing.** The core resolves conversation input from its entry identifier,
verified channel designation and existing conversation binding. The following
routes apply at the selected entry point:

| Inbound                                           | Result                                                                                                                                                                |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A desk identifier                                 | That person's latest session at that desk: an open one continues, a closed one is revived, and with none a new one is created. It becomes the conversation's session. |
| An invitation token                               | The person's account is bound, then their own assistant is reached by the same rule.                                                                                  |
| An identifier that resolves to nothing            | The neutral reply; no session.                                                                                                                                        |
| No identifier, and the conversation has a session | That session, revived when it was closed.                                                                                                                             |
| No identifier, no session, a registered person    | Their own assistant, by the same rule.                                                                                                                                |
| No identifier, no session, anyone else            | The neutral reply; no session.                                                                                                                                        |

A verified designated channel supplies its conversation entry point without a
user-sent token. At token-based entry points, an adapter's bare entry gesture — a
start link without a parameter — from a registered person enters their own
assistant; from anyone else it carries no identifier and routes like any other
message. Entering elsewhere leaves the earlier session as it is; it receives no
more messages from the conversation, and a later entry at its endpoint
continues it. A miss changes nothing, so the conversation stays where it was. A
session is the conversation's session whatever its state while it is open —
starting, active or escalated. A session that carries no endpoint is never
treated as a desk session to return to.

**Misses.** An identifier that resolves to nothing — no such home, a desk that
is not enabled or whose home is not on the master, a desk identifier sent
on Discord, anything that is not exactly an identifier — and a message without
an identifier from a person who is not registered and whose conversation has no
session, get one **neutral reply** and no session. The reply is the same text in
every one of those cases, names no organisation, and is sent at most once per
conversation within a cooldown window. An unrecognised invitation token keeps
the reply member onboarding gives it.

**Unavailability.** The existing fleet resolver must establish one live master
running the relevant adapter before conversational input is accepted. When that
owner is unavailable or conflicting master declarations prevent selection, no
computer starts a conversation, consumes an invitation or answers on behalf of
another owner. The failure is observable to operators. A non-master sends no
fallback conversation reply. The master that cannot start or revive an otherwise
valid endpoint uses the neutral reply and preserves the existing binding.

**Invitations.** Person invitations execute on the master even when requested
from another computer. Their issuance and public endpoint links are owned by
`local/projects/teleclaude/spec/feature/config/person-invitations`.
Old secondary bot addresses are outside conversational entry; their retained
session history is not an alternative live binding.

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
  - Discord: a direct message to the bot consisting of an invitation token.
    Discord carries no desk identifier.
- **Session metadata** — the adapter's origin metadata and the endpoint the
  session was created at.
- **Conversation binding** — the master's durable record of each designated
  adapter conversation's endpoint and session.
- **Resolution result** — the endpoint's working folder.
- **Help-desk entry links** — rendered on the master by
  `telec config company help-desk-links <slug>` and
  `telec config project help-desk-links <slug>`, one per adapter configured
  there that carries desk identifiers.

### Designated conversation channels

A UI adapter's designated conversation channel is a durable entry point to a
personal assistant or help desk. Designation comes from the adapter's established
surface binding and verified participant identity. A provider's generic channel
object alone establishes no designation. Forum posts and explicitly started
sessions keep their independently selected conversations
(`general/policy/human-contract`).

For a designated personal-assistant channel, the core accepts input only when
the sender's verified identity matches the person the channel serves. A mismatch
receives the neutral reply and creates or reaches no session.

The adapter supplies the channel identity and designation to the core conversation
resolver. The core resolves its endpoint and retains the TeleClaude session
binding, open or closed. Text, audio and file input use that same resolution.
Channel selection remains separate from person-wide memory attribution.

At reconciliation and entry, an existing session at a verified designated channel
acquires its resolved endpoint while retaining its TeleClaude identity and native
lineage. Selection uses the established channel binding or the most recently
created eligible matching record, including closed records. Eligibility requires
agreement among the channel designation, participant, endpoint and recorded
session purpose; soft-deleted records, forum conversations and autonomous runs
retain their own lifecycle. Unresolved associations remain observable without
claiming a participant or endpoint
(`general/principle/trust-and-guardrails`).

Every designated conversational channel follows the master ownership and
unavailability rules above. Provider fan-out and the presence of a bot credential
on a peer do not establish a second conversation owner.

Adoption selects the eligible retained conversation on the authoritative host.
Recorded conversations on other computers retain their history and provenance;
they acquire no competing shared-channel binding. Shared-channel cutover settles
accepted work through the existing lifecycle contract and retires competing
channel-delivery associations (`general/principle/trust-and-guardrails`).
Distinct channels remain distinct continuing conversations, even when they
resolve to the same person and assistant endpoint.

### Conversation identity and retention

The TeleClaude session is the durable continuation record. Returning adapter
input reuses the binding for that adapter conversation and endpoint, including
closed sessions. Discovery without an existing binding chooses the most recently
created eligible matching conversation. Background activity does not change
that ordering. Simultaneous first inputs use the existing serialized
resolve-or-create boundary (`sdlc/policy/code-quality-practices`).

An explicit new personal-assistant conversation has its own TeleClaude session
and does not replace an adapter entry point's continuing conversation. Multiple
PA conversations are allowed. Conversation lookup is adapter-specific even when
identity resolves several linked adapters to the same registered person.

Native transcript references remain on the session's existing lineage. Closing
releases execution resources while retaining that record. Soft deletion hides a
record from ordinary selection without discarding its history or relationships.

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
Given several computers receive every WhatsApp message
When a person enters with a company desk's identifier
Then the mesh master records the conversation's binding to that desk
And the person's session at that desk runs on the master
And the person's later messages, files and voice reach that session
And no other computer creates a session or sends a reply
```

#### UC-CE11: A secondary bot is not a conversation entry point

#### UC-CE12: The links command renders a desk's entry links on the master

```gherkin
Given a project whose help desk is enabled
And Telegram, Discord and WhatsApp are configured on the master
When an admin of that project runs the help-desk links command for it on the master
Then a Telegram link and a WhatsApp link are returned, each carrying the desk's identifier
And the Telegram link names the master's bot
And no Discord link is returned
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

#### UC-CE19: An operator can diagnose unavailable conversation ownership

```gherkin
Scenario Outline: conversation ownership is unavailable because <condition>
  Given an operator is responsible for a designated conversation adapter
  And <condition> prevents selection of a unique live master for the adapter
  When the operator checks ownership for that adapter
  Then the operator can see that conversation ownership is unavailable

  Examples:
    | condition                            |
    | no available master for the adapter   |
    | conflicting master declarations      |
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

#### UC-CE25: A person can enter a desk even when its repository is on several computers

#### UC-CE26: Discord carries no desk entry

```gherkin
Scenario Outline: <case>
  Given a registered member whose Discord direct message reaches their own assistant
  And <situation>
  When the member sends <message> as a direct message
  Then <outcome>
  And no session is created at any desk

  Examples:
    | case            | situation                                                | message                         | outcome                                                                        |
    | desk identifier | a company whose help desk is enabled on the master        | that desk's identifier          | they receive the neutral reply and their next direct message reaches their own assistant |
    | earlier binding | their direct message was bound to a session at that desk  | a message without an identifier | the message reaches their own assistant and not the desk session              |
```

#### UC-CE27:

```gherkin
Given a human has a continuing assistant at an adapter entry point
And the human starts a separate personal-assistant conversation
When the human next writes through the original entry point
Then that input continues the entry point's original conversation
And the separate conversation remains independently selectable
```

#### UC-CE28: A person resumes their most recent eligible conversation at an endpoint

```gherkin
Given a person has more than one retained conversation matching their identity and endpoint
And no current conversation binding selects one
When they return to that endpoint
Then the most recently created eligible session resumes as the conversation
And unrelated or soft-deleted sessions remain outside it
```

#### UC-CE29: A designated channel continues its assistant

```gherkin
Given a registered person has a designated personal-assistant channel on a UI adapter
When they send conversation input through that channel
Then the core reaches that channel's assistant endpoint
And the session records the endpoint and channel binding
And subsequent input continues the same TeleClaude session
```

#### UC-CE30: A designated channel revives its closed conversation

```gherkin
Given a designated conversation channel is bound to a closed TeleClaude session
When its person sends text, audio or file input
Then that same session is revived on its owning computer
And the accepted input reaches it through the existing delivery contract
And its response returns to the originating channel
```

#### UC-CE31: Existing channel conversations retain their identity

#### UC-CE32: Channel designation preserves independent conversations

```gherkin
Given a person has two distinct designated assistant channels
And separately started PA and project-forum conversations
When the person writes through one designated channel
Then that channel's retained conversation receives the input
And the other conversations retain their bindings and lifecycle
```

#### UC-CE33: Unresolved channel associations remain unclaimed

#### UC-CE34: A shared designated channel has one conversation owner

#### UC-CE35: Telegram ownership is independent of fan-out

```gherkin
Given a registered person's Telegram conversation reaches the canonical bot on the master
When that person sends a supported conversation input
Then the master resolves its durable conversation binding
And subsequent input continues or revives that TeleClaude session
And receipt by only one provider connection does not change ownership
```

#### UC-CE36: A recorded peer session cannot bypass ownership

### Cross-context references

- **integration** — adapters carry identifiers, channel designations and input
  through the owning core boundary. Provider receiver lifecycle belongs to
  `local/projects/teleclaude/spec/feature/integration/conversation-only-adapters`;
  adapters resolve no endpoint themselves.
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

- Discord carries no identifier in a link: a member sends their invitation
  token as a direct message, which needs a Discord account able to open a direct
  message with the bot.
- WhatsApp pre-fills the identifier but the person must send it unchanged; an
  edited one gets the neutral reply.
- A WhatsApp endpoint answers only from a computer holding WhatsApp send
  credentials, so the master holds them.
- A desk whose home is not present on the master is not hosted anywhere: its
  identifier gets the neutral reply until the home is on the master.
- One WhatsApp business number serves every desk, so a desk link can only
  pre-fill the identifier for the person to send. A desk with its own channel
  identity — its own number or bot — is not supported.

## See Also

- docs/local/adr/0120-discord-is-never-a-customer-surface.md — why Discord carries no desk entry.
