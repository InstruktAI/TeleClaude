---
description: Keeps a person's own memories current as their conversations in their
  home end — one standing agent per person home, so their memories are changed by
  one agent, one ended conversation at a time.
subscriptions:
  - teleclaude.agent_runtime.session.ended.person
subscription_home: person
---

# Person Conversation Memory — Procedure

## Required reads

- @~/.teleclaude/docs/general/procedure/conversation-memory/overview.md

## Goal

When a conversation of this person in their own home ends, keep the memories
about them in their home current, as the conversation memory procedure
describes. This agent is the one standing agent for the person's home: every
ended conversation of theirs reaches it, one at a time.

## Preconditions

- Activated by the end of a session a person held in their own home, working in
  that person's home.

## Steps

1. Run the conversation memory procedure for the ended session, through
   advancing its read point.
2. End the turn. The next ended conversation of this person arrives here as a
   new activation.

## Outputs

- The outputs of the conversation memory procedure for each ended conversation.

## Recovery

- Recovery follows the conversation memory procedure. The next ended
  conversation, or the next end of the same conversation after its revival,
  reads from that session's unchanged read point.
