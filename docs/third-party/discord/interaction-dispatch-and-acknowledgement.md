---
description: Discord component-interaction dispatch and single-acknowledgement semantics, and how discord.py routes a click to a registered persistent view
---

# Discord Interaction Dispatch and Acknowledgement

## Purpose

Document the interaction semantics a bot must respect when more than one gateway
session of the same application is connected, and the view-routing rules
`discord.py` applies to a component click. Complements
`third-party/discord/gateway-delivery-guarantees`, which covers message delivery
and RESUME; this document covers the interaction request/response contract and
the client-side dispatch that precedes it.

## Acknowledgement is single-use and time-boxed

Discord's interaction contract is a pseudo-transaction with exactly one
acknowledgement:

- An initial response **must** be sent within **3 seconds** of receiving the
  event. Discord states: "If the 3 second deadline is exceeded, the token will be
  invalidated." A deferred response (`DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE`,
  type 5) counts as that initial response.
- Interactions received over the gateway are answered over HTTP, never over the
  gateway: "Responses to Interactions are not sent as commands over the gateway."
- After the initial response, the interaction `token` stays valid for **15
  minutes** for followup messages.

The relevant failure codes:

| Code    | Official description                        |
| ------- | ------------------------------------------- |
| `10062` | `Unknown interaction`                       |
| `40060` | `Interaction has already been acknowledged` |

`10062` is what a caller receives when it tries to acknowledge an interaction
whose token is no longer valid — expired past the 3-second window, or already
consumed. The practical consequence: **the acknowledgement is a race that exactly
one caller wins.** Any other caller holding the same interaction gets `10062`
raised out of its response call, before whatever work it intended to do.

## Multiple gateway sessions of one application

A single bot token may hold several concurrent gateway connections — separate
processes, separate hosts, or separate clients in one process. Discord does not
elect one of them as the owner of a component interaction, and offers no
per-session dispatch filter for interactions. Each connected session may receive
the event, so a deployment that runs one bot identity across several hosts must
treat "this event is mine to answer" as an **application-level decision**, made
before acknowledging.

Combined with the single-acknowledgement rule above, the ordering matters: a
session that acknowledges first and decides ownership second has already
consumed the one acknowledgement, and every other session — including the one
that could actually serve the request — fails with `10062`.

## discord.py persistent-view routing

`discord.py` (verified against 2.7.1) routes a component interaction to a
registered view by `(component_type, custom_id)`, checked against two stores in
order:

1. the entry registered for the interaction's **message id**, then
2. a fallback entry registered under **no message id**.

If both miss, the interaction is discarded without dispatch and without any HTTP
call. The fallback lookup is what makes an unscoped registration a catch-all: a
view registered without a message id answers **every** message in the guild whose
buttons share its `custom_id`, including messages the process never created.

`Client.add_view`'s documented contract understates this. The vendor
documentation describes `message_id` only as a state-refresh mechanism — "The
message ID that the view is attached to. This is currently used to refresh the
view's state during message update events. If not given then message update
events are not propagated for the view." — and says nothing about its role in
dispatch keying. That behavior is visible only in the library source
(`discord/ui/view.py`, `ViewStore.dispatch_view`). Treat `message_id` as
scoping which messages a view answers, not merely whether it refreshes.

Consequence for `custom_id` design: a `custom_id` that carries no message,
channel, or instance component is guild-wide-constant, so every registration of
that id competes for every click bearing it.

## Sources

- [Discord Developer Portal — Receiving and Responding to Interactions](https://docs.discord.com/developers/interactions/receiving-and-responding)
- [Discord Developer Portal — Opcodes and Status Codes (JSON error codes)](https://docs.discord.com/developers/topics/opcodes-and-status-codes)
- [Discord Developer Portal — Gateway](https://docs.discord.com/developers/events/gateway)
- [discord.py — `Client.add_view`](https://discordpy.readthedocs.io/en/stable/api.html#discord.Client.add_view)
