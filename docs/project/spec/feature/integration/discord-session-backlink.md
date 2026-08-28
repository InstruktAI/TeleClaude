---
description: Native Discord jump-link construction for a TeleClaude session's Discord
  context — one Discord-owned builder that every surface rendering a session backlink
  consumes.
---

# Discord Session Backlink — Spec

## What it is

One Discord-owned capability that turns a TeleClaude session's stored Discord
identifiers into a native, clickable jump URL. Discord is the mobile
administration surface, so a human reading a Discord-bound message that
originates from a session can jump straight into that session's Discord
context — its forum thread, team channel, or DM channel — without searching.

This capability is the single construction point for Discord session
backlinks.

<!-- planned:session-jump-links -->

Session enumeration carries a listed session's own address, so an agent holds
that address at the moment it has identified the session it cares about.

<!-- /planned:session-jump-links -->

Person-addressed delivery (`telec message`) renders it when the
request carries an originating session; any surface that later renders a
session backlink on Discord (session-output presentation, owner
notifications, operational action cards) constructs it through this same
capability rather than building URLs independently.

## Canonical fields

### URL construction

- Form: `https://discord.com/channels/<guild_id>/<channel_or_thread_id>[/<message_id>]`.
- Identifier precedence: the session's `thread_id` when present, else its
  `channel_id` — the most specific context wins (a forum session stores the
  forum as `channel_id` and its own thread as `thread_id`).
- A channel-bound origin with no stored guild — a DM-scoped session — uses the
  `@me` guild segment: `https://discord.com/channels/@me/<channel_id>`. Such a
  link resolves only for a viewer who participates in that DM.
- A thread-bound origin with no stored guild resolves its guild segment from the
  configured guild. When no guild is configured, no address is constructed and
  the origin takes the observable miss path below.
- The optional trailing `<message_id>` pins a specific message; without it
  the link opens the thread or channel.
- The origin session and its Discord identifiers travel as structured
  metadata — the session's stored `discord` origin section, plus explicit
  arguments for a specific message. A backlink is never inferred from
  message text.
- Rendering fits the backlink within Discord's message length limit: an
  oversized body is trimmed so the appended link always survives intact —
  the body yields, never the link.

### Resolution and observability

- Origin resolution reads the origin session's stored Discord origin
  metadata. An unknown session id, an empty `discord` section, or no usable
  thread/channel identifier makes the backlink unconstructable.
- An unconstructable backlink for a supplied origin is observable: a
  structured, body-free log line records the origin session, the delivery
  target, and the miss reason. The message itself is still delivered,
  without a backlink.
- A message that carries no originating session renders no backlink and
  records no backlink decision.
- A built backlink is recorded as a structured decision after the provider
  send succeeds, carrying the origin session, the destination, and the
  provider's returned message id — so the log line proves the platform
  message carrying the backlink was actually dispatched, and delivery
  behavior is auditable from logs alone. A provider send failure therefore
  produces no built decision; it surfaces through the existing failure
  contract of the consuming surface.

### Use cases

#### UC-DSB-1: Backlink rendered for a resolvable origin

```gherkin
Given a person whose resolved delivery channel is discord
And an originating session whose Discord origin metadata records a guild id and a thread id
When a person-addressed message carrying that origin is delivered
Then the delivered Discord message ends with the native jump link for that guild and thread
And after the provider send succeeds a structured log line records the origin session, the built backlink decision, and the provider's returned message id
```

#### UC-DSB-2: Unconstructable backlink is observable, delivery proceeds

```gherkin
Given a person-addressed discord message carrying an origin session with no stored Discord context
When the message is delivered
Then the message is delivered without a backlink
And a structured, body-free log line records the origin session and the miss reason
```

#### UC-DSB-3: No origin, no decision

```gherkin
Given a person-addressed discord message that carries no originating session
When the message is delivered
Then it renders no backlink
And no backlink decision is logged
```

#### UC-DSB-4: DM-scoped origin builds a direct-message link

```gherkin
Given an originating session whose Discord origin metadata records a channel id and no guild id
When a person-addressed message carrying that origin is delivered on discord
Then the delivered message ends with the @me-form jump link for that DM channel
```

## Known caveats

- Construction does not verify viewer permission: Discord resolves the link
  only for viewers with access to the target guild, channel, or DM.
- Any delayed or queued Discord delivery carries the structured origin and
  identifiers through retry — a redelivery renders the same backlink from
  the same structured metadata, never from a re-parse of message text.
- The backlink targets Discord context only, and what decides constructability
  is whether the session has stored a Discord destination — never how the
  session was started or where its input arrives. A session of any origin is
  addressable once that context exists, and a session without it resolves to
  the observable miss path whatever its origin. No cross-platform link is
  constructed.

## See Also

- docs/project/spec/messaging.md — person-addressed delivery, the first consuming surface.
- docs/project/spec/feature/integration/outbound-messaging-providers.md — the provider send primitives beneath the consuming surfaces.
