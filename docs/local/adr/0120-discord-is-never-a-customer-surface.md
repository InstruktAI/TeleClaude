---
visibility: public
number: 0120
date: 2026-10-10
description: Discord is a members-only surface. It carries no help-desk entry, so no desk session ever runs in a Discord conversation.
---

# Discord Is Never a Customer Surface — ADR

## Context

Discord serves the platform's own people. Members reach their personal
assistant by direct message to the bot, and each help desk is reflected into its
own guild category, visible only to the people in that desk's scope, where they
watch every session at the desk and take its escalations.

Conversation entry also let a desk identifier sent to the bot by direct message
open a session at that desk. Only people who share a guild with the bot can open
that direct message, so in practice the visitor was always a member. A session
opened that way has its direct message as its one Discord destination, so it
cannot also appear in its desk's forum without a second Discord destination per
session, with its own delivery lane and cursors. Without that, the desk's scope
never sees the session, and an escalation from it has no forum thread to point
at.

## Decision

Discord is for members only and never for customers. It carries no help-desk
entry: a desk identifier sent on Discord is a miss, and a Discord conversation is
never bound to a desk session. Customers reach help desks through the
customer-facing adapters only, Telegram and WhatsApp.

## Consequences

- Every desk session reaches its desk through an adapter other than Discord, so
  every one of them can be mirrored into its desk's forum through the single
  Discord destination a session has.
- Discord's role is unambiguous: a member's own conversation and the scoped desk
  surfaces. A member who wants to try a desk as a visitor does so through Telegram
  or WhatsApp, as a customer would.
- The help-desk links command renders no Discord link.
- A direct message that was bound to a desk session stops reaching it; the member's
  next direct message reaches their own assistant.
- A public or community presence on Discord, such as a company's fan server, is
  not supported. It would need a new decision about which guilds the bot serves
  and how their conversations are reflected.

## Alternatives Considered

- **Keep Discord entry and mirror those sessions into the desk's forum.** Meets
  every desk-surface outcome, but needs a second Discord destination per session
  in the delivery pipeline, for an entry path whose only users are members.
- **Keep Discord entry and leave those sessions out of the desk's forum.** The
  smallest change, but the desk's scope cannot see those sessions, an escalation
  from one has no thread to link, and Discord stays half a customer surface.
